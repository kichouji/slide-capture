"""アプリ本体: タスクトレイ・メニュー・各機能の結び付け (F-17〜F-26)。

スレッド構成:
- メインスレッド: tkinter (範囲指定・ダイアログ)。他スレッドからの操作は ``call_soon`` で受け取る
- pystray スレッド: トレイアイコンとメニュー
- 監視スレッド: Monitor の監視ループ
- pynput / watchdog のスレッド: ホットキー、設定ファイルの変更監視
"""

from __future__ import annotations

import logging
import os
import queue
import subprocess
import threading
import tkinter as tk
from collections.abc import Callable
from pathlib import Path

import pystray
from pystray import Menu, MenuItem

from . import autostart
from .capture import ScreenGrabber
from .config import SENSITIVITIES, SENSITIVITY_LABELS, ConfigManager, Settings
from .hotkeys import HotkeyManager, display_name
from .icons import icon
from .monitor import Monitor, MonitorError, State, StopReason
from .overlay import ask_directory, select_region, show_region_frame
from .session import export_pdf

log = logging.getLogger(__name__)

TITLE = "スライド自動キャプチャ"
_STATE_ICON = {State.STOPPED: "stopped", State.RUNNING: "running", State.PAUSED: "paused"}


class App:
    def __init__(self, config: ConfigManager) -> None:
        self.config = config
        self.root = tk.Tk()
        self.root.withdraw()
        self._queue: queue.Queue[Callable[[], None]] = queue.Queue()
        self._selecting = False
        self._flash_job: str | None = None

        self.monitor = Monitor(lambda: self.config.settings, self, ScreenGrabber)
        self.hotkeys = HotkeyManager(
            {
                "start_stop": lambda: self.call_soon(self.toggle_start),
                "pause_resume": lambda: self.call_soon(self.monitor.toggle_pause),
                "capture_now": lambda: self.call_soon(self.monitor.capture_now),
                "select_region": lambda: self.call_soon(self.select_region),
            }
        )
        self.icon = pystray.Icon("slide_capture", icon("stopped"), TITLE, menu=self._build_menu())
        self.config.add_listener(self._on_settings_changed)

    # --- 起動と終了 ---------------------------------------------------------

    def run(self) -> None:
        self.icon.run_detached()
        self.config.start_watching(on_error=lambda msg: self.notify(msg, "設定ファイル"))
        self._apply_hotkeys(self.config.settings)
        self._sync_autostart(self.config.settings)
        if self.config.warnings:
            self.root.after(
                1500, lambda: self.notify("\n".join(self.config.warnings), "設定ファイル")
            )
        if self.config.settings.region is None:
            self.root.after(
                1500,
                lambda: self.notify("メニューの「撮影範囲を指定」から撮影範囲を指定してください。"),
            )
        self.root.after(100, self._drain_queue)
        self.root.after(15000, self._refresh_menu)
        log.info("起動しました (設定: %s)", self.config.path)
        try:
            self.root.mainloop()
        finally:
            self._shutdown()

    def quit(self) -> None:
        self.monitor.stop(StopReason.USER)
        self.root.quit()

    def _shutdown(self) -> None:
        self.hotkeys.stop()
        self.config.stop_watching()
        self.icon.stop()
        log.info("終了しました")

    # --- スレッド間の受け渡し -------------------------------------------------

    def call_soon(self, fn: Callable[[], None]) -> None:
        """任意のスレッドから、tkinter のメインスレッドで fn を実行させる。"""
        self._queue.put(fn)

    def _drain_queue(self) -> None:
        while True:
            try:
                fn = self._queue.get_nowait()
            except queue.Empty:
                break
            try:
                fn()
            except Exception as e:
                log.exception("操作の実行中にエラーが発生しました")
                self.notify(f"エラーが発生しました: {e}")
        self.root.after(100, self._drain_queue)

    def _refresh_menu(self) -> None:
        """メニューの経過時間表示を定期的に更新する。"""
        if self.monitor.state is not State.STOPPED:
            self.icon.update_menu()
        self.root.after(15000, self._refresh_menu)

    def _action(self, fn: Callable[[], None]) -> Callable[..., None]:
        """メニューのコールバックを、メインスレッドで実行するよう包む。"""
        return lambda *_: self.call_soon(fn)

    # --- 操作 -------------------------------------------------------------

    def start(self) -> None:
        if self.config.settings.region is None:
            self.notify("撮影範囲が未指定です。範囲を指定してから開始します。")
            self.select_region(start_after=True)
            return
        try:
            self.monitor.start()
        except MonitorError as e:
            self.notify(str(e))

    def toggle_start(self) -> None:
        if self.monitor.state is State.STOPPED:
            self.start()
        else:
            self.monitor.stop(StopReason.USER)

    def select_region(self, start_after: bool = False) -> None:
        if self._selecting:
            return
        self._selecting = True
        try:
            region = select_region(self.root)
        finally:
            self._selecting = False
        if region is None:
            return
        self.config.set_region(region)
        show_region_frame(self.root, region)
        log.info("撮影範囲を設定しました: %s", region)
        if start_after:
            self.start()

    def show_region(self) -> None:
        region = self.config.settings.region
        if region:
            show_region_frame(self.root, region)

    def set_sensitivity(self, key: str) -> None:
        self.config.update("detection", "sensitivity", key)

    def change_output_dir(self) -> None:
        path = ask_directory(self.root, str(self.config.settings.output_path))
        if path:
            self.config.update("session", "output_dir", str(Path(path)))
            if self.monitor.state is not State.STOPPED:
                self.notify("新しい保存先は、次のセッションから使われます。")

    def open_output_dir(self) -> None:
        folder = (
            self.monitor.session.folder
            if self.monitor.session
            else self.config.settings.output_path
        )
        folder.mkdir(parents=True, exist_ok=True)
        os.startfile(folder)

    def open_config(self) -> None:
        subprocess.Popen(["notepad.exe", str(self.config.path)])

    def toggle_autostart(self) -> None:
        self.config.update("app", "autostart", not self.config.settings.autostart)

    def make_pdf_now(self) -> None:
        folder = self.monitor.session.folder if self.monitor.session else self.monitor.last_folder
        if folder:
            self._export_pdf_async(folder)

    def _export_pdf_async(self, folder: Path) -> None:
        def work() -> None:
            try:
                out = export_pdf(folder)
            except Exception as e:
                log.exception("PDF を作成できません")
                self.notify(f"PDF を作成できません: {e}")
                return
            if out:
                self.notify(f"PDF を作成しました: {out.name}")
            else:
                self.notify("PDF にする画像がありません。")

        # 終了時も PDF の書き出しを完了させるため daemon にしない
        threading.Thread(target=work, name="pdf-export").start()

    # --- Monitor からの通知 (MonitorListener) ---------------------------------

    def on_state_changed(self, state: State, count: int) -> None:
        self.icon.icon = icon(_STATE_ICON[state])
        self.icon.update_menu()

    def on_saved(self, path: Path, count: int, trigger: str) -> None:
        self.icon.update_menu()
        self.call_soon(self._flash_icon)
        if self.config.settings.notify_on_save:
            self.notify(f"{count} 枚目を保存しました ({path.name})")

    def on_stopped(self, reason: StopReason, folder: Path | None, count: int) -> None:
        if reason is StopReason.MAX_DURATION:
            minutes = self.config.settings.max_duration_min
            self.notify(
                f"最大監視時間({_format_minutes(minutes)})に達したため、自動停止しました。"
                f"保存枚数: {count} 枚"
            )
        elif reason is StopReason.IDLE:
            self.notify(f"画面の変化がない状態が続いたため、自動停止しました。保存枚数: {count} 枚")
        elif reason is StopReason.USER:
            self.notify(f"停止しました。保存枚数: {count} 枚")
        if folder and count > 0 and self.config.settings.export_pdf_on_stop:
            self._export_pdf_async(folder)

    def on_idle_warning(self, minutes: float) -> None:
        self.notify(f"画面の変化がない状態が {_format_minutes(minutes)} 続いています。")

    def on_error(self, message: str) -> None:
        self.notify(message)

    # --- 表示 -------------------------------------------------------------

    def notify(self, message: str, title: str = TITLE) -> None:
        log.info("通知: %s", message)
        try:
            self.icon.notify(message[:255], title)
        except Exception:
            log.exception("通知を表示できません")

    def _flash_icon(self) -> None:
        """保存した瞬間だけアイコンを緑にする (F-24)。"""
        if self._flash_job:
            self.root.after_cancel(self._flash_job)
        self.icon.icon = icon("saved")

        def restore() -> None:
            self._flash_job = None
            self.icon.icon = icon(_STATE_ICON[self.monitor.state])

        self._flash_job = self.root.after(700, restore)

    def _status_text(self) -> str:
        state = self.monitor.state
        if state is State.STOPPED:
            return f"状態: {state.value}"
        minutes = int(self.monitor.active_seconds() // 60)
        return f"状態: {state.value}(保存 {self.monitor.count} 枚・{minutes} 分経過)"

    def _label(self, text: str, hotkey_name: str) -> Callable[[MenuItem], str]:
        def make(_: MenuItem) -> str:
            combo = self.config.settings.hotkeys.get(hotkey_name, "")
            return f"{text}\t{display_name(combo)}" if combo else text

        return make

    def _build_menu(self) -> Menu:
        state = lambda: self.monitor.state  # noqa: E731
        sensitivity_items = [
            MenuItem(
                SENSITIVITY_LABELS[key],
                self._action(lambda key=key: self.set_sensitivity(key)),
                checked=lambda _, key=key: self.config.settings.sensitivity == key,
                radio=True,
            )
            for key in SENSITIVITIES
        ]
        return Menu(
            MenuItem(lambda _: self._status_text(), None, enabled=False),
            Menu.SEPARATOR,
            MenuItem(
                self._label("開始", "start_stop"),
                self._action(self.start),
                visible=lambda _: state() is State.STOPPED,
            ),
            MenuItem(
                self._label("停止", "start_stop"),
                self._action(lambda: self.monitor.stop(StopReason.USER)),
                visible=lambda _: state() is not State.STOPPED,
            ),
            MenuItem(
                self._label("一時停止", "pause_resume"),
                self._action(self.monitor.pause),
                visible=lambda _: state() is State.RUNNING,
            ),
            MenuItem(
                self._label("再開", "pause_resume"),
                self._action(self.monitor.resume),
                visible=lambda _: state() is State.PAUSED,
            ),
            MenuItem(
                self._label("今すぐ撮影", "capture_now"),
                self._action(self.monitor.capture_now),
                enabled=lambda _: state() is State.RUNNING,
            ),
            Menu.SEPARATOR,
            MenuItem(
                self._label("撮影範囲を指定...", "select_region"), self._action(self.select_region)
            ),
            MenuItem(
                "撮影範囲を表示",
                self._action(self.show_region),
                enabled=lambda _: self.config.settings.region is not None,
            ),
            MenuItem("感度", Menu(*sensitivity_items)),
            MenuItem("保存先を変更...", self._action(self.change_output_dir)),
            MenuItem("保存先フォルダを開く", self._action(self.open_output_dir)),
            MenuItem(
                "PDF を作成",
                self._action(self.make_pdf_now),
                enabled=lambda _: (
                    self.monitor.session is not None or self.monitor.last_folder is not None
                ),
            ),
            Menu.SEPARATOR,
            MenuItem("設定ファイルを開く", self._action(self.open_config)),
            MenuItem(
                "Windows 起動時に自動起動",
                self._action(self.toggle_autostart),
                checked=lambda _: self.config.settings.autostart,
            ),
            Menu.SEPARATOR,
            MenuItem("終了", self._action(self.quit)),
        )

    # --- 設定の反映 ----------------------------------------------------------

    def _on_settings_changed(self, old: Settings, new: Settings) -> None:
        if old.hotkeys != new.hotkeys:
            self._apply_hotkeys(new)
        if old.autostart != new.autostart:
            self._sync_autostart(new)
        self.icon.update_menu()

    def _apply_hotkeys(self, s: Settings) -> None:
        errors = self.hotkeys.apply(s.hotkeys)
        if errors:
            self.notify("\n".join(errors), "ホットキー")

    def _sync_autostart(self, s: Settings) -> None:
        try:
            if autostart.is_enabled() != s.autostart:
                autostart.set_enabled(s.autostart)
        except OSError as e:
            log.exception("自動起動の設定に失敗しました")
            self.notify(f"自動起動を設定できません: {e}")


def _format_minutes(minutes: float) -> str:
    if minutes >= 60 and minutes % 60 == 0:
        return f"{int(minutes // 60)} 時間"
    return f"{minutes:g} 分"

"""設定ファイルの読み書きと変更監視 (F-02, F-29〜F-32)。

設定は TOML 形式で、メモ帳などで直接編集できる。アプリから値を変更するときは
tomlkit を使い、ユーザが書いたコメントや並び順を保ったまま書き戻す。
"""

from __future__ import annotations

import logging
import os
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import tomlkit
from tomlkit.toml_document import TOMLDocument

log = logging.getLogger(__name__)

APP_NAME = "slide-capture"
SENSITIVITIES = ("high", "standard", "low")
SENSITIVITY_LABELS = {"high": "高", "standard": "標準", "low": "低"}
IDLE_ACTIONS = ("warn", "stop", "none")
HOTKEY_ACTIONS = ("start_stop", "pause_resume", "capture_now", "select_region")


def app_data_dir() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    return Path(base) / APP_NAME


def default_config_path() -> Path:
    override = os.environ.get("SLIDE_CAPTURE_CONFIG")
    return Path(override) if override else app_data_dir() / "config.toml"


def default_output_dir() -> Path:
    return Path.home() / "Pictures" / "SlideCapture"


@dataclass(frozen=True)
class Region:
    left: int
    top: int
    width: int
    height: int

    def as_dict(self) -> dict[str, int]:
        return {"left": self.left, "top": self.top, "width": self.width, "height": self.height}


@dataclass(frozen=True)
class Settings:
    region: Region | None = None
    interval_sec: float = 1.0

    sensitivity: str = "standard"
    threshold_high: float = 0.01
    threshold_standard: float = 0.03
    threshold_low: float = 0.08
    pixel_threshold: int = 24
    compare_width: int = 320
    stable_threshold: float = 0.005
    settle_sec: float = 2.0
    settle_max_sec: float = 10.0
    skip_duplicates: bool = True

    output_dir: str = ""
    max_duration_min: float = 120.0
    idle_timeout_min: float = 30.0
    idle_action: str = "warn"
    export_pdf_on_stop: bool = True

    hotkey_start_stop: str = "<ctrl>+<alt>+s"
    hotkey_pause_resume: str = "<ctrl>+<alt>+p"
    hotkey_capture_now: str = "<ctrl>+<alt>+c"
    hotkey_select_region: str = "<ctrl>+<alt>+r"

    notify_on_save: bool = False
    autostart: bool = False

    @property
    def change_threshold(self) -> float:
        return {
            "high": self.threshold_high,
            "standard": self.threshold_standard,
            "low": self.threshold_low,
        }[self.sensitivity]

    @property
    def output_path(self) -> Path:
        return Path(self.output_dir).expanduser() if self.output_dir else default_output_dir()

    @property
    def hotkeys(self) -> dict[str, str]:
        return {name: getattr(self, f"hotkey_{name}") for name in HOTKEY_ACTIONS}


TEMPLATE = """\
# スライド自動キャプチャ 設定ファイル
# メモ帳などで直接編集できます。保存すると、アプリを再起動しなくても反映されます。

[capture]
# 撮影範囲(画面座標・ピクセル)。メニューの「撮影範囲を指定」で設定されます。
# region = { left = 0, top = 0, width = 1280, height = 720 }

# 監視間隔(秒)
interval_sec = 1.0

[detection]
# 感度: "high"(高) / "standard"(標準) / "low"(低)
sensitivity = "standard"

# 感度ごとの、変化したとみなす画素の割合(0〜1)。小さいほど小さな変化にも反応します。
threshold_high = 0.01
threshold_standard = 0.03
threshold_low = 0.08

# 画素が変化したとみなす明るさの差(0〜255)。大きくすると動画の画質ノイズを無視しやすくなります。
pixel_threshold = 24

# 比較のために縮小する画像の幅(ピクセル)
compare_width = 320

# 画面が落ち着いたとみなす、連続するフレーム間の変化の割合(0〜1)
stable_threshold = 0.005

# 変化を検知してから、画面が落ち着くまで待つ時間(秒)。この時間変化がなければ撮影します。
settle_sec = 2.0

# 画面が落ち着かない場合でも撮影するまでの最大待ち時間(秒)。0 で無制限に待ちます。
settle_max_sec = 10.0

# 保存済みのどの画像とも同じ内容なら保存しない(true / false)
skip_duplicates = true

[session]
# 保存先フォルダ。この下にセッションごとのフォルダが作られます。
output_dir = ""

# 最大監視時間(分)。到達すると自動で停止します。一時停止中の時間は含みません。
max_duration_min = 120

# 画面に変化がない状態がこの時間(分)続いたら idle_action を実行します。
idle_timeout_min = 30

# "warn"(通知する) / "stop"(自動停止する) / "none"(何もしない)
idle_action = "warn"

# 停止時に、保存した画像をまとめた PDF を作成する
export_pdf_on_stop = true

[hotkeys]
# 例: "<ctrl>+<alt>+s"。空文字 "" にするとそのホットキーは無効になります。
start_stop = "<ctrl>+<alt>+s"
pause_resume = "<ctrl>+<alt>+p"
capture_now = "<ctrl>+<alt>+c"
select_region = "<ctrl>+<alt>+r"

[app]
# 画像を保存するたびに通知を表示する
notify_on_save = false

# Windows の起動時にアプリを自動で起動する
autostart = false
"""

# (セクション, キー, Settings のフィールド名)
_FIELDS: list[tuple[str, str, str]] = [
    ("capture", "interval_sec", "interval_sec"),
    ("detection", "sensitivity", "sensitivity"),
    ("detection", "threshold_high", "threshold_high"),
    ("detection", "threshold_standard", "threshold_standard"),
    ("detection", "threshold_low", "threshold_low"),
    ("detection", "pixel_threshold", "pixel_threshold"),
    ("detection", "compare_width", "compare_width"),
    ("detection", "stable_threshold", "stable_threshold"),
    ("detection", "settle_sec", "settle_sec"),
    ("detection", "settle_max_sec", "settle_max_sec"),
    ("detection", "skip_duplicates", "skip_duplicates"),
    ("session", "output_dir", "output_dir"),
    ("session", "max_duration_min", "max_duration_min"),
    ("session", "idle_timeout_min", "idle_timeout_min"),
    ("session", "idle_action", "idle_action"),
    ("session", "export_pdf_on_stop", "export_pdf_on_stop"),
    *(("hotkeys", name, f"hotkey_{name}") for name in HOTKEY_ACTIONS),
    ("app", "notify_on_save", "notify_on_save"),
    ("app", "autostart", "autostart"),
]

_DEFAULTS = Settings()

# 値の範囲チェック。範囲外は既定値を使う
_VALID: dict[str, Callable[[Any], bool]] = {
    "interval_sec": lambda v: 0.1 <= v <= 60,
    "sensitivity": lambda v: v in SENSITIVITIES,
    "threshold_high": lambda v: 0 < v <= 1,
    "threshold_standard": lambda v: 0 < v <= 1,
    "threshold_low": lambda v: 0 < v <= 1,
    "pixel_threshold": lambda v: 0 <= v <= 255,
    "compare_width": lambda v: v >= 16,
    "stable_threshold": lambda v: 0 <= v <= 1,
    "settle_sec": lambda v: v >= 0,
    "settle_max_sec": lambda v: v >= 0,
    "max_duration_min": lambda v: v > 0,
    "idle_timeout_min": lambda v: v > 0,
    "idle_action": lambda v: v in IDLE_ACTIONS,
}


def _coerce(value: Any, default: Any) -> Any:
    """TOML の値を既定値と同じ型に変換する。変換できなければ ValueError。"""
    if isinstance(default, bool):
        if isinstance(value, bool):
            return value
        raise ValueError(f"true / false で指定してください: {value!r}")
    if isinstance(default, int):
        if isinstance(value, bool):
            raise ValueError(f"整数で指定してください: {value!r}")
        return int(value)
    if isinstance(default, float):
        if isinstance(value, bool):
            raise ValueError(f"数値で指定してください: {value!r}")
        return float(value)
    if isinstance(default, str):
        if not isinstance(value, str):
            raise ValueError(f"文字列で指定してください: {value!r}")
        return value
    return value


def parse_settings(doc: TOMLDocument) -> tuple[Settings, list[str]]:
    """TOML ドキュメントから Settings を作る。問題のある値は既定値にし、警告として返す。"""
    values: dict[str, Any] = {}
    warnings: list[str] = []
    data = doc.unwrap()

    for section, key, name in _FIELDS:
        table = data.get(section)
        if not isinstance(table, dict) or key not in table:
            continue
        default = getattr(_DEFAULTS, name)
        try:
            value = _coerce(table[key], default)
            check = _VALID.get(name)
            if check and not check(value):
                raise ValueError(f"範囲外の値です: {value!r}")
        except (TypeError, ValueError) as e:
            warnings.append(f"[{section}] {key}: {e}(既定値 {default!r} を使います)")
            continue
        values[name] = value

    region_data = (
        data.get("capture", {}).get("region") if isinstance(data.get("capture"), dict) else None
    )
    if region_data is not None:
        try:
            region = Region(
                int(region_data["left"]),
                int(region_data["top"]),
                int(region_data["width"]),
                int(region_data["height"]),
            )
            if region.width <= 0 or region.height <= 0:
                raise ValueError("幅と高さは1以上にしてください")
            values["region"] = region
        except (KeyError, TypeError, ValueError) as e:
            warnings.append(f"[capture] region: {e}(撮影範囲は未指定として扱います)")

    return Settings(**values), warnings


class ConfigError(Exception):
    pass


Listener = Callable[[Settings, Settings], None]


class ConfigManager:
    """設定ファイルを保持し、変更をリスナーへ通知する。"""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or default_config_path()
        self._lock = threading.RLock()
        self._listeners: list[Listener] = []
        self._last_text: str | None = None
        self._observer = None
        self._debounce: threading.Timer | None = None
        self.warnings: list[str] = []
        self._doc, self._settings = self._load_or_create()

    @property
    def settings(self) -> Settings:
        return self._settings

    def add_listener(self, fn: Listener) -> None:
        self._listeners.append(fn)

    # --- 読み込み ---------------------------------------------------------

    def _load_or_create(self) -> tuple[TOMLDocument, Settings]:
        if not self.path.exists():
            self.path.parent.mkdir(parents=True, exist_ok=True)
            doc = tomlkit.parse(TEMPLATE)
            doc["session"]["output_dir"] = str(default_output_dir())  # type: ignore[index]
            self._write(doc)
            log.info("設定ファイルを作成しました: %s", self.path)
        text = self.path.read_text(encoding="utf-8-sig")
        try:
            doc = tomlkit.parse(text)
        except Exception as e:
            # 起動時に壊れていた場合は既定値で起動し、ファイルは上書きしない
            log.error("設定ファイルを読み込めません: %s", e)
            self.warnings = [f"設定ファイルの書式に誤りがあるため、既定値で起動します: {e}"]
            self._last_text = text
            return tomlkit.parse(TEMPLATE), Settings()
        self._last_text = text
        settings, self.warnings = parse_settings(doc)
        return doc, settings

    def reload(self) -> bool:
        """ファイルを読み直す。内容が変わっていれば True。書式エラーは ConfigError。"""
        with self._lock:
            try:
                text = self.path.read_text(encoding="utf-8-sig")
            except OSError as e:
                raise ConfigError(f"設定ファイルを読み込めません: {e}") from e
            if text == self._last_text:
                return False
            try:
                doc = tomlkit.parse(text)
            except Exception as e:
                raise ConfigError(f"設定ファイルの書式に誤りがあります: {e}") from e
            self._last_text = text
            settings, self.warnings = parse_settings(doc)
            old, self._doc, self._settings = self._settings, doc, settings
        log.info("設定ファイルを再読み込みしました")
        self._notify(old, settings)
        return True

    # --- 書き込み ---------------------------------------------------------

    def _write(self, doc: TOMLDocument) -> None:
        text = tomlkit.dumps(doc)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, self.path)
        self._last_text = text

    def update(self, section: str, key: str, value: Any) -> None:
        """1つの値を変更してファイルへ書き戻す。"""
        with self._lock:
            if section not in self._doc:
                self._doc[section] = tomlkit.table()
            self._doc[section][key] = value  # type: ignore[index]
            self._write(self._doc)
            old = self._settings
            self._settings, self.warnings = parse_settings(self._doc)
            new = self._settings
        self._notify(old, new)

    def set_region(self, region: Region) -> None:
        table = tomlkit.inline_table()
        table.update(region.as_dict())
        self.update("capture", "region", table)

    def _notify(self, old: Settings, new: Settings) -> None:
        if old == new:
            return
        for fn in list(self._listeners):
            try:
                fn(old, new)
            except Exception:
                log.exception("設定変更の通知でエラーが発生しました")

    # --- 変更監視 (F-31) ---------------------------------------------------

    def start_watching(self, on_error: Callable[[str], None]) -> None:
        from watchdog.events import FileSystemEvent, FileSystemEventHandler
        from watchdog.observers import Observer

        target = self.path.resolve()

        def schedule_reload() -> None:
            if self._debounce:
                self._debounce.cancel()
            self._debounce = threading.Timer(0.5, run_reload)
            self._debounce.daemon = True
            self._debounce.start()

        def run_reload() -> None:
            try:
                self.reload()
            except ConfigError as e:
                log.warning("%s", e)
                on_error(str(e))

        class Handler(FileSystemEventHandler):
            def on_any_event(self, event: FileSystemEvent) -> None:
                paths = [event.src_path, getattr(event, "dest_path", "")]
                if any(p and Path(os.fsdecode(p)).resolve() == target for p in paths):
                    schedule_reload()

        self._observer = Observer()
        self._observer.schedule(Handler(), str(target.parent), recursive=False)
        self._observer.daemon = True
        self._observer.start()

    def stop_watching(self) -> None:
        if self._observer:
            self._observer.stop()
            self._observer = None
        if self._debounce:
            self._debounce.cancel()

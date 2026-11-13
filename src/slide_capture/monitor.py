"""監視ループとセッションの状態管理 (F-05〜F-07, F-18, F-19, F-34〜F-40)。"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Protocol

from PIL import Image

from .config import Region, Settings
from .detector import Action, ChangeDetector, DetectorParams, change_ratio, to_signature
from .session import Session

log = logging.getLogger(__name__)


class State(Enum):
    STOPPED = "停止中"
    RUNNING = "監視中"
    PAUSED = "一時停止"


class StopReason(Enum):
    USER = "user"
    MAX_DURATION = "max_duration"
    IDLE = "idle"
    ERROR = "error"


class Grabber(Protocol):
    def grab(self, region: Region) -> Image.Image: ...
    def close(self) -> None: ...


class MonitorListener(Protocol):
    def on_state_changed(self, state: State, count: int) -> None: ...
    def on_saved(self, path: Path, count: int, trigger: str) -> None: ...
    def on_stopped(self, reason: StopReason, folder: Path | None, count: int) -> None: ...
    def on_idle_warning(self, minutes: float) -> None: ...
    def on_error(self, message: str) -> None: ...


class MonitorError(Exception):
    pass


def detector_params(s: Settings) -> DetectorParams:
    return DetectorParams(
        change_threshold=s.change_threshold,
        pixel_threshold=s.pixel_threshold,
        stable_threshold=s.stable_threshold,
        settle_sec=s.settle_sec,
        settle_max_sec=s.settle_max_sec,
        skip_duplicates=s.skip_duplicates,
    )


@dataclass
class _Run:
    """1回の監視スレッドに対応する制御用オブジェクト。"""

    stop: threading.Event
    wake: threading.Event
    thread: threading.Thread | None = None


class Monitor:
    def __init__(
        self,
        get_settings: Callable[[], Settings],
        listener: MonitorListener,
        grabber_factory: Callable[[], Grabber],
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._get_settings = get_settings
        self._listener = listener
        self._grabber_factory = grabber_factory
        self._clock = clock
        self._lock = threading.RLock()

        self.state = State.STOPPED
        self.session: Session | None = None
        self.last_folder: Path | None = None
        self.detector = ChangeDetector()
        self._run: _Run | None = None
        self._manual_requested = False

        self._session_start = 0.0
        self._active_sec = 0.0
        self._active_mark = 0.0
        self._last_activity = 0.0  # 画面に動きがあった時点のアクティブ時間
        self._idle_warned = False
        self._error_reported = False

    # --- 状態 -------------------------------------------------------------

    @property
    def count(self) -> int:
        return self.session.count if self.session else 0

    def active_seconds(self) -> float:
        """一時停止中を除いた監視時間。"""
        with self._lock:
            if self.state is State.RUNNING:
                return self._active_sec + (self._clock() - self._active_mark)
            return self._active_sec

    def _accumulate(self, now: float) -> None:
        if self.state is State.RUNNING:
            self._active_sec += now - self._active_mark
        self._active_mark = now

    # --- 操作 -------------------------------------------------------------

    def start(self, *, spawn_thread: bool = True) -> None:
        with self._lock:
            if self.state is not State.STOPPED:
                return
            s = self._get_settings()
            if s.region is None:
                raise MonitorError(
                    "撮影範囲が指定されていません。先に「撮影範囲を指定」を行ってください。"
                )
            try:
                self.session = Session(s.output_path)
            except OSError as e:
                raise MonitorError(f"保存先フォルダを作成できません: {e}") from e
            now = self._clock()
            self.detector.reset()
            self._session_start = now
            self._active_sec = 0.0
            self._active_mark = now
            self._last_activity = 0.0
            self._idle_warned = False
            self._error_reported = False
            self._manual_requested = False
            self.state = State.RUNNING
            run = self._run = _Run(threading.Event(), threading.Event())
            if spawn_thread:
                run.thread = threading.Thread(
                    target=self._loop, args=(run,), name="monitor", daemon=True
                )
                run.thread.start()
            count = self.count
            log.info("セッションを開始しました: %s", self.session.folder)
        self._listener.on_state_changed(State.RUNNING, count)

    def pause(self) -> None:
        with self._lock:
            if self.state is not State.RUNNING:
                return
            self._accumulate(self._clock())
            self.state = State.PAUSED
            self.detector.interrupt()
            count = self.count
        self._listener.on_state_changed(State.PAUSED, count)

    def resume(self) -> None:
        with self._lock:
            if self.state is not State.PAUSED:
                return
            self._active_mark = self._clock()
            self.state = State.RUNNING
            count = self.count
            if self._run:
                self._run.wake.set()
        self._listener.on_state_changed(State.RUNNING, count)

    def toggle_pause(self) -> None:
        if self.state is State.RUNNING:
            self.pause()
        elif self.state is State.PAUSED:
            self.resume()

    def capture_now(self) -> None:
        with self._lock:
            if self.state is not State.RUNNING or not self._run:
                return
            self._manual_requested = True
            self._run.wake.set()

    def stop(self, reason: StopReason = StopReason.USER) -> None:
        with self._lock:
            if self.state is State.STOPPED:
                return
            self._accumulate(self._clock())
            self.state = State.STOPPED
            run, self._run = self._run, None
            session, self.session = self.session, None
            if run:
                run.stop.set()
                run.wake.set()
            folder = session.folder if session else None
            count = session.count if session else 0
            if session:
                session.close()
            self.last_folder = folder
            log.info("セッションを停止しました (%s, %d 枚)", reason.value, count)
        if run and run.thread and run.thread is not threading.current_thread():
            run.thread.join(timeout=5)
        self._listener.on_state_changed(State.STOPPED, 0)
        self._listener.on_stopped(reason, folder, count)

    # --- 監視ループ ----------------------------------------------------------

    def _loop(self, run: _Run) -> None:
        try:
            grabber = self._grabber_factory()
        except Exception as e:
            log.exception("キャプチャの初期化に失敗しました")
            self._listener.on_error(f"画面キャプチャを開始できません: {e}")
            self.stop(StopReason.ERROR)
            return
        try:
            next_tick = self._clock()
            while not run.stop.is_set():
                self.tick(grabber)
                interval = self._get_settings().interval_sec
                next_tick += interval
                now = self._clock()
                if next_tick < now:  # 処理が遅れた場合は追いつこうとしない
                    next_tick = now + interval
                run.wake.wait(next_tick - now)
                run.wake.clear()
        finally:
            grabber.close()

    def tick(self, grabber: Grabber) -> None:
        """1回分の監視処理。テストから直接呼べるよう公開している。"""
        s = self._get_settings()
        with self._lock:
            if self.state is not State.RUNNING or self.session is None or s.region is None:
                return
            manual, self._manual_requested = self._manual_requested, False

        try:
            img = grabber.grab(s.region)
        except Exception as e:
            log.warning("キャプチャに失敗しました: %s", e)
            if not self._error_reported:
                self._error_reported = True
                self._listener.on_error(f"画面をキャプチャできません: {e}")
            return
        self._error_reported = False
        sig = to_signature(img, s.compare_width)

        saved: tuple[Path, int, str] | None = None
        stop_reason: StopReason | None = None
        idle_warning = False
        with self._lock:
            if self.state is not State.RUNNING or self.session is None:
                return
            now = self._clock()
            self._accumulate(now)

            if manual:
                change = (
                    0.0
                    if self.detector.reference is None
                    else change_ratio(sig, self.detector.reference, s.pixel_threshold)
                )
                saved = self._save(img, now, change, "manual")
                self.detector.commit(sig)
                self.detector.interrupt()
                self._last_activity = self._active_sec
            else:
                decision = self.detector.feed(sig, now, detector_params(s))
                if decision.motion > s.stable_threshold or decision.action is Action.SAVE:
                    self._last_activity = self._active_sec
                    self._idle_warned = False
                if decision.action is Action.SAVE:
                    saved = self._save(img, now, decision.change, decision.reason)
                    self.detector.commit(sig)

            if self._active_sec >= s.max_duration_min * 60:
                stop_reason = StopReason.MAX_DURATION
            elif s.idle_action != "none" and (
                self._active_sec - self._last_activity >= s.idle_timeout_min * 60
            ):
                if s.idle_action == "stop":
                    stop_reason = StopReason.IDLE
                elif not self._idle_warned:
                    self._idle_warned = True
                    idle_warning = True

        if saved:
            self._listener.on_saved(*saved)
        if idle_warning:
            self._listener.on_idle_warning(s.idle_timeout_min)
        if stop_reason:
            self.stop(stop_reason)

    def _save(
        self, img: Image.Image, now: float, change: float, trigger: str
    ) -> tuple[Path, int, str] | None:
        assert self.session is not None
        try:
            path = self.session.save(
                img,
                elapsed_sec=now - self._session_start,
                change=change,
                trigger=trigger,
                captured_at=datetime.now(),
            )
        except OSError as e:
            log.exception("画像を保存できません")
            self._listener.on_error(f"画像を保存できません: {e}")
            return None
        log.info("保存しました: %s (変化 %.1f%%, %s)", path.name, change * 100, trigger)
        return path, self.session.count, trigger

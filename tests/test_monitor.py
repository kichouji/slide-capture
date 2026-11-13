from dataclasses import replace
from pathlib import Path

import pytest

from slide_capture.config import Region, Settings
from slide_capture.monitor import Monitor, MonitorError, State, StopReason

from .helpers import FakeClock, slide


class FakeGrabber:
    def __init__(self) -> None:
        self.frame = slide(1)

    def grab(self, region):
        return self.frame

    def close(self):
        pass


class Recorder:
    def __init__(self) -> None:
        self.events = []

    def on_state_changed(self, state, count):
        self.events.append(("state", state))

    def on_saved(self, path, count, trigger):
        self.events.append(("saved", count, trigger))

    def on_stopped(self, reason, folder, count):
        self.events.append(("stopped", reason, count))

    def on_idle_warning(self, minutes):
        self.events.append(("idle",))

    def on_error(self, message):
        self.events.append(("error", message))

    def of(self, kind):
        return [e for e in self.events if e[0] == kind]


@pytest.fixture
def env(tmp_path):
    settings = {
        "s": Settings(region=Region(0, 0, 320, 180), output_dir=str(tmp_path), settle_sec=2.0)
    }
    clock = FakeClock()
    rec = Recorder()
    grabber = FakeGrabber()
    mon = Monitor(lambda: settings["s"], rec, lambda: grabber, clock=clock)

    def step(frame=None, sec=1.0):
        if frame is not None:
            grabber.frame = frame
        mon.tick(grabber)
        clock.advance(sec)

    return mon, rec, grabber, clock, settings, step


def test_start_requires_region(env):
    mon, _, _, _, settings, _ = env
    settings["s"] = replace(settings["s"], region=None)
    with pytest.raises(MonitorError):
        mon.start(spawn_thread=False)


def test_session_flow_saves_on_change(env):
    mon, rec, _, _, _, step = env
    mon.start(spawn_thread=False)
    step(slide(1))
    for _ in range(4):
        step(slide(2))
    assert [e[1] for e in rec.of("saved")] == [1, 2]
    folder = mon.session.folder
    mon.stop()
    assert rec.of("stopped") == [("stopped", StopReason.USER, 2)]
    assert len(list(Path(folder).glob("*.png"))) == 2
    assert (Path(folder) / "log.csv").exists()
    assert mon.state is State.STOPPED


def test_pause_skips_capture_and_resume_compares_with_previous(env):
    mon, rec, _, clock, _, step = env
    mon.start(spawn_thread=False)
    step(slide(1))
    mon.pause()
    for _ in range(5):
        step(slide(2))  # 一時停止中は撮影しない
    assert len(rec.of("saved")) == 1
    mon.resume()
    for _ in range(4):
        step(slide(2))  # 一時停止前の画像と比べて変化を検知する
    assert len(rec.of("saved")) == 2


def test_manual_capture(env):
    mon, rec, grabber, _, _, step = env
    mon.start(spawn_thread=False)
    step(slide(1))
    mon._run.wake.clear()
    mon.capture_now()
    step(slide(1))  # 同じ画面でも手動撮影は保存する
    assert rec.of("saved")[-1] == ("saved", 2, "manual")


def test_auto_stop_at_max_duration_excluding_pause(env):
    mon, rec, _, clock, settings, step = env
    settings["s"] = replace(settings["s"], max_duration_min=1)
    mon.start(spawn_thread=False)
    for _ in range(30):
        step(slide(1))
    mon.pause()
    clock.advance(600)  # 一時停止中の時間は数えない
    mon.resume()
    assert mon.state is State.RUNNING
    for _ in range(31):
        step(slide(1))
    assert mon.state is State.STOPPED
    assert rec.of("stopped") == [("stopped", StopReason.MAX_DURATION, 1)]


def test_idle_warning_and_stop(env):
    mon, rec, _, _, settings, step = env
    settings["s"] = replace(settings["s"], idle_timeout_min=1, idle_action="warn")
    mon.start(spawn_thread=False)
    for _ in range(70):
        step(slide(1))
    assert len(rec.of("idle")) == 1  # 1回だけ警告
    assert mon.state is State.RUNNING

    settings["s"] = replace(settings["s"], idle_action="stop")
    step(slide(1))
    assert rec.of("stopped") == [("stopped", StopReason.IDLE, 1)]

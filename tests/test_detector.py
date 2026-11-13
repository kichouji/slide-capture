from PIL import Image, ImageDraw

from slide_capture.detector import (
    Action,
    ChangeDetector,
    DetectorParams,
    change_ratio,
    to_signature,
)

from .helpers import slide

P = DetectorParams(settle_sec=2.0, settle_max_sec=10.0)


def sig(img):
    return to_signature(img, 160)


def run(det, frames, start=0.0, step=1.0, params=P):
    """フレーム列を1秒間隔で流し、(時刻, 決定) のうち保存したものを返す。"""
    saves = []
    t = start
    for f in frames:
        s = sig(f)
        d = det.feed(s, t, params)
        if d.action is Action.SAVE:
            det.commit(s)
            saves.append((t, d))
        t += step
    return saves


def test_change_ratio_identical_and_different():
    a = sig(slide(1))
    assert change_ratio(a, a, 24) == 0.0
    assert change_ratio(a, sig(slide(2)), 24) > 0.03
    assert change_ratio(a, sig(slide(1, (200, 100))), 24) == 1.0  # サイズ違い


def test_first_frame_is_saved_immediately():
    det = ChangeDetector()
    saves = run(det, [slide(1)])
    assert len(saves) == 1 and saves[0][1].reason == "first"


def test_waits_until_screen_settles():
    det = ChangeDetector()
    # 0秒: 1枚目, 1秒〜: 2枚目に切り替わり、そのまま
    saves = run(det, [slide(1), slide(2), slide(2), slide(2), slide(2)])
    assert [t for t, _ in saves] == [0.0, 3.0]  # 検知(1秒)から2秒落ち着いたら撮影


def test_transition_frames_are_not_saved():
    det = ChangeDetector()
    # 切り替え途中の画面 (3, 4) が続いた後、5 で落ち着く
    frames = [slide(1), slide(3), slide(4), slide(5), slide(5), slide(5)]
    saves = run(det, frames)
    assert len(saves) == 2
    t, _ = saves[1]
    assert t == 5.0  # slide(5) が出た 3秒から 2秒後
    assert change_ratio(det.reference, sig(slide(5)), 24) == 0.0


def test_reverted_change_is_not_saved():
    det = ChangeDetector()
    # 一瞬だけ別の画面が出て元に戻る (F-09)
    saves = run(det, [slide(1), slide(2), slide(1), slide(1), slide(1), slide(1)])
    assert len(saves) == 1


def test_small_change_is_ignored():
    base = slide(1)
    small = base.copy()
    ImageDraw.Draw(small).rectangle((300, 0, 305, 5), fill="red")  # 小さなマウスカーソル程度
    det = ChangeDetector()
    saves = run(det, [base, small, small, small, small])
    assert len(saves) == 1


def test_duplicate_of_earlier_slide_is_skipped():
    det = ChangeDetector()
    frames = [slide(1)] + [slide(2)] * 4 + [slide(1)] * 4 + [slide(2)] * 4
    saves = run(det, frames)
    assert len(saves) == 2  # 1, 2 のみ。戻った 1 と再度の 2 は保存しない (F-10)


def test_duplicate_saved_when_dedupe_disabled():
    det = ChangeDetector()
    params = DetectorParams(settle_sec=2.0, skip_duplicates=False)
    frames = [slide(1)] + [slide(2)] * 4 + [slide(1)] * 4
    saves = run(det, frames, params=params)
    assert len(saves) == 3


def test_saves_after_max_wait_even_if_never_settles():
    det = ChangeDetector()
    params = DetectorParams(settle_sec=2.0, settle_max_sec=5.0)
    frames = [slide(1)] + [slide(10 + i) for i in range(10)]  # 毎秒内容が変わり続ける
    saves = run(det, frames, params=params)
    assert len(saves) >= 2
    assert saves[1][1].reason == "timeout"
    assert saves[1][0] == 6.0  # 1秒で検知 → 5秒後


def test_sensitivity_threshold():
    base = Image.new("RGB", (320, 180), "white")
    changed = base.copy()
    ImageDraw.Draw(changed).rectangle((0, 0, 60, 30), fill="black")  # 約3%の変化
    ratio = change_ratio(sig(base), sig(changed), 24)
    assert 0.01 < ratio < 0.08
    for threshold, expected in [(0.01, 2), (0.08, 1)]:
        det = ChangeDetector()
        params = DetectorParams(change_threshold=threshold, settle_sec=1.0)
        assert len(run(det, [base, changed, changed, changed], params=params)) == expected


def test_interrupt_keeps_reference():
    det = ChangeDetector()
    run(det, [slide(1)])
    ref = det.reference
    det.feed(sig(slide(2)), 1.0, P)
    assert det.settling
    det.interrupt()  # 一時停止
    assert not det.settling and det.reference is ref
    # 再開後、一時停止前の基準と比べて変化を検知する (F-36)
    saves = run(det, [slide(2)] * 4, start=100.0)
    assert len(saves) == 1

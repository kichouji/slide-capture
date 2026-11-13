"""開発環境のスモークテスト: 主要依存ライブラリが読み込めることを確認する。"""


def test_imports():
    import tkinter  # noqa: F401

    import img2pdf  # noqa: F401
    import mss  # noqa: F401
    import numpy  # noqa: F401
    import pynput  # noqa: F401
    import pystray  # noqa: F401
    import tomlkit  # noqa: F401
    import watchdog  # noqa: F401
    from PIL import Image  # noqa: F401


def test_screen_grab():
    import mss

    with mss.MSS() as sct:
        shot = sct.grab({"left": 0, "top": 0, "width": 10, "height": 10})
    assert shot.size == (10, 10)

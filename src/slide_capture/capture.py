"""画面範囲のキャプチャ。"""

from __future__ import annotations

import mss
from PIL import Image

from .config import Region


class ScreenGrabber:
    """mss のラッパー。mss のインスタンスは作成したスレッドでのみ使うこと。"""

    def __init__(self) -> None:
        self._sct = mss.MSS()

    def grab(self, region: Region) -> Image.Image:
        shot = self._sct.grab(region.as_dict())
        return Image.frombytes("RGB", shot.size, shot.rgb)

    def close(self) -> None:
        self._sct.close()

    def __enter__(self) -> ScreenGrabber:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

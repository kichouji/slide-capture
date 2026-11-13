from __future__ import annotations

from PIL import Image, ImageDraw


def slide(n: int, size: tuple[int, int] = (320, 180)) -> Image.Image:
    """番号ごとに内容の異なるテスト用スライド画像。"""
    img = Image.new("RGB", size, "white")
    d = ImageDraw.Draw(img)
    w, h = size
    # 番号に応じて異なる位置に大きなブロックを描く
    x = (n * 53) % (w - 100)
    y = (n * 31) % (h - 60)
    d.rectangle((x, y, x + 100, y + 60), fill="black")
    d.rectangle((0, h - 20, (n * 37) % w + 20, h), fill=(0, 0, 200))
    return img


class FakeClock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t

    def advance(self, sec: float) -> None:
        self.t += sec

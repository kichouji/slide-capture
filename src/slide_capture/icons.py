"""タスクトレイのアイコン画像 (F-23, F-24)。状態ごとに色と形を変える。"""

from __future__ import annotations

from functools import cache

from PIL import Image, ImageDraw

SIZE = 64


def _base(color: str) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle((2, 2, SIZE - 3, SIZE - 3), radius=12, fill=color)
    return img, draw


@cache
def icon(kind: str) -> Image.Image:
    """kind: "stopped" / "running" / "paused" / "saved" """
    if kind == "running":  # 赤地に白丸(録画中)
        img, d = _base("#d93025")
        d.ellipse((18, 18, 46, 46), fill="white")
    elif kind == "paused":  # 黄色地に一時停止マーク
        img, d = _base("#f29900")
        d.rectangle((20, 17, 28, 47), fill="white")
        d.rectangle((36, 17, 44, 47), fill="white")
    elif kind == "saved":  # 緑地にチェック(保存した瞬間)
        img, d = _base("#188038")
        d.line((17, 33, 28, 44, 47, 21), fill="white", width=7, joint="curve")
    else:  # 灰色地に四角(停止中)
        img, d = _base("#5f6368")
        d.rectangle((21, 21, 43, 43), fill="white")
    return img

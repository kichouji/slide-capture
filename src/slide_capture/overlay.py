"""撮影範囲の指定 (F-01) と確認用の枠線表示 (F-04)。tkinter のメインスレッドで呼ぶこと。"""

from __future__ import annotations

import tkinter as tk
from tkinter import filedialog

from .config import Region
from .winutil import virtual_screen

MIN_SIZE = 16
FRAME_COLOR = "#ff3b30"


def select_region(root: tk.Tk) -> Region | None:
    """画面全体を暗くしたオーバーレイを表示し、ドラッグで矩形を選ばせる。Esc で取り消し。"""
    vx, vy, vw, vh = virtual_screen()
    win = tk.Toplevel(root)
    win.overrideredirect(True)
    win.attributes("-topmost", True)
    win.attributes("-alpha", 0.35)
    win.geometry(f"{vw}x{vh}+{vx}+{vy}")
    win.configure(cursor="crosshair")

    canvas = tk.Canvas(win, bg="black", highlightthickness=0)
    canvas.pack(fill="both", expand=True)
    canvas.create_text(
        -vx + 40,
        -vy + 40,
        anchor="nw",
        fill="white",
        font=("Yu Gothic UI", 20, "bold"),
        text="撮影する範囲をドラッグで指定してください(Esc / 右クリックで取り消し)",
    )

    result: dict[str, Region | None] = {"region": None}
    start: dict[str, int] = {}
    rect: dict[str, int] = {}

    def on_press(e: tk.Event) -> None:
        start["x"], start["y"] = e.x_root, e.y_root
        if "id" in rect:
            canvas.delete(rect["id"])
        rect["id"] = canvas.create_rectangle(
            e.x_root - vx,
            e.y_root - vy,
            e.x_root - vx,
            e.y_root - vy,
            outline=FRAME_COLOR,
            width=3,
            fill="white",
        )

    def on_drag(e: tk.Event) -> None:
        if "id" in rect:
            canvas.coords(
                rect["id"], start["x"] - vx, start["y"] - vy, e.x_root - vx, e.y_root - vy
            )

    def on_release(e: tk.Event) -> None:
        if not start:
            return
        left, right = sorted((start["x"], e.x_root))
        top, bottom = sorted((start["y"], e.y_root))
        if right - left >= MIN_SIZE and bottom - top >= MIN_SIZE:
            result["region"] = Region(left, top, right - left, bottom - top)
            win.destroy()
        else:
            start.clear()
            if "id" in rect:
                canvas.delete(rect.pop("id"))

    canvas.bind("<ButtonPress-1>", on_press)
    canvas.bind("<B1-Motion>", on_drag)
    canvas.bind("<ButtonRelease-1>", on_release)
    win.bind("<Escape>", lambda e: win.destroy())
    canvas.bind("<ButtonPress-3>", lambda e: win.destroy())

    win.after(50, win.focus_force)
    win.grab_set()
    root.wait_window(win)
    return result["region"]


def show_region_frame(
    root: tk.Tk, region: Region, seconds: float = 3.0, thickness: int = 4
) -> None:
    """撮影範囲の外側に枠線を一定時間表示する。枠線自体は撮影範囲に写り込まない。"""
    t = thickness
    x, y, w, h = region.left, region.top, region.width, region.height
    bars = [
        (x - t, y - t, w + 2 * t, t),  # 上
        (x - t, y + h, w + 2 * t, t),  # 下
        (x - t, y, t, h),  # 左
        (x + w, y, t, h),  # 右
    ]
    windows = []
    for bx, by, bw, bh in bars:
        bar = tk.Toplevel(root)
        bar.overrideredirect(True)
        bar.attributes("-topmost", True)
        bar.configure(bg=FRAME_COLOR)
        bar.geometry(f"{bw}x{bh}+{bx}+{by}")
        windows.append(bar)

    def close() -> None:
        for bar in windows:
            bar.destroy()

    root.after(int(seconds * 1000), close)


def ask_directory(root: tk.Tk, initial: str) -> str | None:
    """フォルダ選択ダイアログ。取り消された場合は None。"""
    holder = tk.Toplevel(root)
    holder.withdraw()
    holder.attributes("-topmost", True)
    try:
        path = filedialog.askdirectory(
            parent=holder, initialdir=initial, title="保存先フォルダを選択", mustexist=False
        )
    finally:
        holder.destroy()
    return path or None

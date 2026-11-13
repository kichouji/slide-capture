"""Windows 固有の小さなユーティリティ。"""

from __future__ import annotations

import contextlib
import ctypes
import sys

ERROR_ALREADY_EXISTS = 183


def enable_dpi_awareness() -> None:
    """画面座標を物理ピクセルで扱うため、DPI 対応を宣言する。

    tkinter で指定した範囲と mss でキャプチャする範囲の座標を一致させるために、
    Tk を作成する前に呼ぶ必要がある。
    """
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # Per-monitor DPI aware
    except (AttributeError, OSError):
        with contextlib.suppress(AttributeError, OSError):
            ctypes.windll.user32.SetProcessDPIAware()


def virtual_screen() -> tuple[int, int, int, int]:
    """全モニタを合わせた仮想スクリーンの (left, top, width, height)。"""
    if sys.platform != "win32":
        return (0, 0, 1920, 1080)
    m = ctypes.windll.user32.GetSystemMetrics
    return (m(76), m(77), m(78), m(79))


class SingleInstance:
    """名前付きミューテックスで多重起動を防ぐ。"""

    def __init__(self, name: str) -> None:
        self._handle = None
        self.already_running = False
        if sys.platform != "win32":
            return
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateMutexW.restype = ctypes.c_void_p
        self._handle = kernel32.CreateMutexW(None, False, name)
        self.already_running = ctypes.get_last_error() == ERROR_ALREADY_EXISTS
        self._kernel32 = kernel32

    def release(self) -> None:
        if self._handle:
            self._kernel32.CloseHandle(ctypes.c_void_p(self._handle))
            self._handle = None

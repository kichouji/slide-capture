"""グローバルホットキー (F-27, F-28)。"""

from __future__ import annotations

import logging
from collections.abc import Callable

from pynput import keyboard

log = logging.getLogger(__name__)


def display_name(combo: str) -> str:
    """ホットキー表記をメニュー表示用に整える。例: "<ctrl>+<alt>+s" → "Ctrl+Alt+S" """
    parts = []
    for part in combo.split("+"):
        part = part.strip().strip("<>")
        parts.append(part.upper() if len(part) == 1 else part.capitalize())
    return "+".join(parts)


class HotkeyManager:
    def __init__(self, handlers: dict[str, Callable[[], None]]) -> None:
        self._handlers = handlers
        self._listener: keyboard.GlobalHotKeys | None = None

    def apply(self, bindings: dict[str, str]) -> list[str]:
        """割り当てをやり直す。解釈できなかった割り当てをエラーメッセージとして返す。"""
        self.stop()
        mapping: dict[str, Callable[[], None]] = {}
        errors: list[str] = []
        for name, combo in bindings.items():
            combo = combo.strip().lower()
            if not combo or name not in self._handlers:
                continue
            try:
                keyboard.HotKey.parse(combo)
            except ValueError:
                errors.append(f"ホットキー {name} の指定 {combo!r} を解釈できません")
                continue
            if combo in mapping:
                errors.append(f"ホットキー {combo!r} が重複しています")
                continue
            mapping[combo] = self._handlers[name]
        if mapping:
            self._listener = keyboard.GlobalHotKeys(mapping)
            self._listener.daemon = True
            self._listener.start()
            log.info("ホットキーを登録しました: %s", ", ".join(mapping))
        return errors

    def stop(self) -> None:
        if self._listener:
            self._listener.stop()
            self._listener = None

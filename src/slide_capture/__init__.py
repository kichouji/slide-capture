"""スライド自動キャプチャ: 画面の指定範囲を監視し、変化時に自動でスクリーンショットを保存する。"""

from __future__ import annotations

import argparse
import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

__version__ = "0.1.0"


def _setup_logging(log_dir: Path, debug: bool) -> None:
    log_dir.mkdir(parents=True, exist_ok=True)
    handlers: list[logging.Handler] = [
        RotatingFileHandler(
            log_dir / "app.log", maxBytes=1_000_000, backupCount=2, encoding="utf-8"
        )
    ]
    if sys.stderr is not None:  # pythonw で起動した場合は stderr がない
        handlers.append(logging.StreamHandler())
    logging.basicConfig(
        level=logging.DEBUG if debug else logging.INFO,
        format="%(asctime)s %(levelname)s [%(threadName)s] %(name)s: %(message)s",
        handlers=handlers,
    )


def main() -> None:
    parser = argparse.ArgumentParser(prog="slide-capture", description=__doc__)
    parser.add_argument("--config", type=Path, help="設定ファイルのパス")
    parser.add_argument("--debug", action="store_true", help="詳細なログを出力する")
    args = parser.parse_args()

    from .config import ConfigManager, app_data_dir
    from .winutil import SingleInstance, enable_dpi_awareness

    _setup_logging(app_data_dir(), args.debug)
    instance = SingleInstance("Local\\SlideCaptureApp")
    if instance.already_running:
        logging.getLogger(__name__).warning("すでに起動しています")
        return

    # Tk と mss の座標を一致させるため、ウィンドウを作る前に呼ぶ
    enable_dpi_awareness()

    from .app import App

    try:
        App(ConfigManager(args.config)).run()
    finally:
        instance.release()

"""セッション単位の画像保存・ログ・PDF 出力 (F-11〜F-16, F-25)。"""

from __future__ import annotations

import csv
import logging
import threading
from datetime import datetime
from pathlib import Path

import img2pdf
from PIL import Image

log = logging.getLogger(__name__)

LOG_FILENAME = "log.csv"
LOG_HEADER = ["連番", "ファイル名", "撮影時刻", "経過時間", "変化の大きさ(%)", "種別"]


def format_elapsed(seconds: float, sep: str = ":") -> str:
    total = max(0, int(seconds))
    h, rest = divmod(total, 3600)
    m, s = divmod(rest, 60)
    return f"{h:02d}{sep}{m:02d}{sep}{s:02d}"


def image_filename(seq: int, elapsed_sec: float) -> str:
    """例: 0001_00-12-34.png (連番_セッション開始からの経過時間)"""
    return f"{seq:04d}_{format_elapsed(elapsed_sec, '-')}.png"


def session_images(folder: Path) -> list[Path]:
    return sorted(p for p in folder.glob("[0-9]*.png") if p.is_file())


def export_pdf(folder: Path) -> Path | None:
    """セッションフォルダ内の画像を1つの PDF にまとめる。画像がなければ None。"""
    images = session_images(folder)
    if not images:
        return None
    out = folder / f"{folder.name}.pdf"
    tmp = out.with_suffix(".pdf.tmp")
    with open(tmp, "wb") as f:
        f.write(img2pdf.convert([str(p) for p in images]))
    tmp.replace(out)
    log.info("PDF を作成しました: %s (%d 枚)", out, len(images))
    return out


class Session:
    """1回の「開始」から「停止」までの保存先フォルダとログ。"""

    def __init__(self, output_root: Path, started_at: datetime | None = None) -> None:
        self.started_at = started_at or datetime.now()
        self.folder = self._make_folder(output_root, self.started_at)
        self.count = 0
        self._lock = threading.Lock()
        # セッション中は開いたまま追記するため、with は使わない
        self._log_file = open(  # noqa: SIM115
            self.folder / LOG_FILENAME, "w", encoding="utf-8-sig", newline=""
        )
        self._csv = csv.writer(self._log_file)
        self._csv.writerow(LOG_HEADER)
        self._log_file.flush()

    @staticmethod
    def _make_folder(root: Path, started_at: datetime) -> Path:
        root.mkdir(parents=True, exist_ok=True)
        base = started_at.strftime("%Y%m%d_%H%M%S")
        folder = root / base
        n = 2
        while folder.exists():
            folder = root / f"{base}_{n}"
            n += 1
        folder.mkdir()
        return folder

    def save(
        self,
        img: Image.Image,
        *,
        elapsed_sec: float,
        change: float,
        trigger: str,
        captured_at: datetime | None = None,
    ) -> Path:
        with self._lock:
            seq = self.count + 1
            path = self.folder / image_filename(seq, elapsed_sec)
            img.save(path, "PNG")
            self.count = seq
            captured_at = captured_at or datetime.now()
            self._csv.writerow(
                [
                    seq,
                    path.name,
                    captured_at.isoformat(sep=" ", timespec="seconds"),
                    format_elapsed(elapsed_sec),
                    f"{change * 100:.2f}",
                    trigger,
                ]
            )
            self._log_file.flush()
            return path

    def close(self) -> None:
        with self._lock:
            if not self._log_file.closed:
                self._log_file.close()

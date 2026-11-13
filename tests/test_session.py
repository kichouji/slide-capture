import csv
from datetime import datetime

from slide_capture.session import Session, export_pdf, format_elapsed, image_filename

from .helpers import slide


def test_filename_contains_sequence_and_elapsed():
    assert image_filename(1, 0) == "0001_00-00-00.png"
    assert image_filename(12, 3723.9) == "0012_01-02-03.png"
    assert format_elapsed(59) == "00:00:59"


def test_session_saves_images_log_and_pdf(tmp_path):
    started = datetime(2026, 11, 14, 9, 30, 0)
    s = Session(tmp_path, started)
    assert s.folder.name == "20261114_093000"
    s.save(slide(1), elapsed_sec=0, change=1.0, trigger="first")
    s.save(slide(2), elapsed_sec=65, change=0.1234, trigger="manual")
    s.close()

    assert sorted(p.name for p in s.folder.glob("*.png")) == [
        "0001_00-00-00.png",
        "0002_00-01-05.png",
    ]
    with open(s.folder / "log.csv", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.reader(f))
    assert rows[0][0] == "連番"
    assert rows[2][0] == "2" and rows[2][3] == "00:01:05" and rows[2][4] == "12.34"

    pdf = export_pdf(s.folder)
    assert pdf is not None and pdf.read_bytes().startswith(b"%PDF")


def test_same_start_time_creates_separate_folder(tmp_path):
    started = datetime(2026, 11, 14, 9, 30, 0)
    a = Session(tmp_path, started)
    b = Session(tmp_path, started)
    a.close()
    b.close()
    assert a.folder != b.folder


def test_export_pdf_without_images(tmp_path):
    s = Session(tmp_path)
    s.close()
    assert export_pdf(s.folder) is None

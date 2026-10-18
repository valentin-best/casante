import io
from types import SimpleNamespace

import cv2
import numpy as np
import pytest
from PIL import Image

from app.pipeline import ocr
from app.pipeline.ingest import IngestResult, Line, Page


def box(x0: float, y0: float, x1: float, y1: float) -> list[list[float]]:
    return [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]


@pytest.fixture
def engine(monkeypatch):
    """Replace RapidOCR with a fake that returns the lines a test sets."""
    fake = SimpleNamespace(lines=[], calls=0)

    def run(image):
        fake.calls += 1
        if not fake.lines:
            return SimpleNamespace(boxes=None, txts=None)
        return SimpleNamespace(
            boxes=np.array([box(*bbox) for _, bbox in fake.lines], dtype=np.float32),
            txts=tuple(text for text, _ in fake.lines),
        )

    monkeypatch.setattr(ocr, "_engine", lambda: run)
    return fake


def jpeg(rgb: np.ndarray, orientation: int | None = None) -> bytes:
    image = Image.fromarray(rgb)
    exif = Image.Exif()
    if orientation:
        exif[0x0112] = orientation
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", exif=exif)
    return buffer.getvalue()


def tilted_page(angle: float = 7) -> np.ndarray:
    """A white 600x800 sheet with dark text bars, rotated on a dark table."""
    table = np.full((1200, 1000, 3), (60, 40, 20), dtype=np.uint8)
    sheet = np.full((800, 600, 3), 255, dtype=np.uint8)
    for y in range(100, 700, 60):
        cv2.rectangle(sheet, (60, y), (500, y + 20), (0, 0, 0), -1)
    table[200:1000, 200:800] = sheet
    matrix = cv2.getRotationMatrix2D((500, 600), angle, 1)
    return cv2.warpAffine(table, matrix, (1000, 1200), borderValue=(60, 40, 20))


def test_reading_order_reads_rows_left_to_right():
    lines = [
        ("Body text", [100, 300, 600, 320]),
        ("21 Willow Creek Way", [800, 102, 1100, 122]),
        ("Willow Creek Physicians", [100, 100, 500, 130]),
        ("Tel 555-479-8850", [850, 130, 1100, 150]),
    ]
    assert [text for text, _ in ocr.reading_order(lines)] == [
        "Willow Creek Physicians",
        "21 Willow Creek Way",
        "Tel 555-479-8850",
        "Body text",
    ]


def test_flatten_page_straightens_the_sheet():
    flat = ocr.flatten_page(tilted_page())

    height, width = flat.shape[:2]
    assert abs(width - 600) < 15 and abs(height - 800) < 15
    # The table is gone: the edges are paper, not brown
    edges = np.concatenate(
        [flat[5, 5:-5], flat[-5, 5:-5], flat[5:-5, 5], flat[5:-5, -5]]
    )
    assert edges.mean() > 200


def test_flatten_page_keeps_photo_without_a_sheet():
    photo = np.full((400, 300, 3), (60, 40, 20), dtype=np.uint8)
    photo[10:60, 10:60] = 255  # a small bright patch, not a page

    assert ocr.flatten_page(photo) is photo


def test_clean_photo_turns_photo_upright():
    landscape = np.full((300, 400, 3), 255, dtype=np.uint8)

    # Orientation 6: the camera was held sideways
    height, width = ocr.clean_photo(jpeg(landscape, orientation=6)).shape[:2]

    assert height > width


def test_clean_photo_shrinks_large_photos():
    big = np.full((3000, 2400, 3), 255, dtype=np.uint8)

    assert max(ocr.clean_photo(jpeg(big)).shape[:2]) <= ocr.MAX_PAGE_SIDE


def test_ingest_photo_saves_page_and_numbers_lines(tmp_path, engine):
    engine.lines = [
        ("Naproxen 220 mg once daily", [50, 400, 450, 420]),
        ("Current medication", [50, 300, 300, 330]),
        ("   ", [50, 500, 60, 510]),
    ]

    result = ocr.ingest_photo(jpeg(tilted_page()), tmp_path)

    [page] = result.pages
    assert page.number == 1 and page.needs_ocr
    assert Image.open(page.image_path).size == (page.width, page.height)
    assert [(line.id, line.text) for line in page.lines] == [
        ("p1-L1", "Current medication"),
        ("p1-L2", "Naproxen 220 mg once daily"),
    ]
    assert page.lines[0].bbox == [50, 300, 300, 330]


def test_ingest_photo_without_text_has_no_lines(tmp_path, engine):
    result = ocr.ingest_photo(jpeg(tilted_page()), tmp_path)

    assert result.pages[0].lines == []


def test_read_scanned_pages_only_reads_pages_without_text(tmp_path, engine):
    engine.lines = [("Penicillin allergy", [10, 10, 200, 30])]
    image = tmp_path / "page.png"
    Image.new("RGB", (100, 100), "white").save(image)
    text_line = Line(id="p1-L1", page=1, text="Typed text", bbox=[0, 0, 1, 1])
    result = IngestResult(
        file_hash="a" * 64,
        pages=[
            Page(
                number=1,
                width=100,
                height=100,
                image_path=str(image),
                lines=[text_line],
                needs_ocr=False,
            ),
            Page(
                number=2,
                width=100,
                height=100,
                image_path=str(image),
                lines=[],
                needs_ocr=True,
            ),
        ],
    )

    pages = ocr.read_scanned_pages(result).pages

    assert engine.calls == 1
    assert pages[0].lines == [text_line]
    assert [(line.id, line.text) for line in pages[1].lines] == [
        ("p2-L1", "Penicillin allergy")
    ]

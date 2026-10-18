"""Photos and scanned pages -> the same numbered lines with boxes as ingest_pdf.

A photo is cleaned before OCR: turned upright, flattened to the sheet of paper and
given more contrast. The cleaned image becomes the page image, so line boxes are in
its pixels and the source viewer's highlights land on the text OCR read.
"""

from __future__ import annotations

import io
import threading
from collections.abc import Sequence
from functools import cache
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PIL import Image, ImageOps

from app.pipeline.ingest import IngestResult, Line, Page, sha256_hex

# Longest side of a cleaned photo: PDF pages render at about 1241x1754 (150 dpi).
MAX_PAGE_SIDE = 2000
# Text detection runs on a copy scaled to this; recognition reads the full image.
DETECT_SIDE = 1280
# The paper must cover this share of the photo, or the photo is used as it is.
MIN_PAGE_AREA = 0.3

# One page at a time: each OCR call can briefly use several hundred MB.
_lock = threading.Lock()


@cache
def _engine() -> Any:
    from rapidocr import RapidOCR

    return RapidOCR(
        params={
            "Global.log_level": "warning",
            # Flattened pages are upright, so skip the upside-down text check
            "Global.use_cls": False,
            "Det.limit_type": "max",
            "Det.limit_side_len": DETECT_SIDE,
        }
    )


def load_engine() -> None:
    """Load the models at startup so the first upload doesn't wait for them."""
    _engine()


def _read_lines(rgb: np.ndarray, page_no: int) -> list[Line]:
    with _lock:
        result = _engine()(cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR))
    if result.boxes is None:
        return []
    found = [
        (text.strip(), [float(v) for v in (*box.min(axis=0), *box.max(axis=0))])
        for box, text in zip(result.boxes, result.txts)
        if text.strip()
    ]
    return [
        Line(
            id=f"p{page_no}-L{n}",
            page=page_no,
            text=text,
            bbox=[round(v, 1) for v in bbox],
        )
        for n, (text, bbox) in enumerate(reading_order(found), start=1)
    ]


def reading_order(
    lines: Sequence[tuple[str, Sequence[float]]],
) -> list[tuple[str, Sequence[float]]]:
    """Top to bottom; lines whose middles are within half a line height share a row
    and read left to right, like a letterhead's name and address."""
    rows: list[list[tuple[str, Sequence[float]]]] = []
    for line in sorted(lines, key=lambda line: line[1][1] + line[1][3]):
        _, (_, y0, _, y1) = line
        if rows:
            _, (_, ry0, _, ry1) = rows[-1][0]
            if abs((y0 + y1) - (ry0 + ry1)) / 2 < min(y1 - y0, ry1 - ry0) / 2:
                rows[-1].append(line)
                continue
        rows.append([line])
    return [line for row in rows for line in sorted(row, key=lambda line: line[1][0])]


def _corners(points: np.ndarray) -> np.ndarray:
    """Top-left, top-right, bottom-right, bottom-left."""
    sums = points.sum(axis=1)
    diffs = np.diff(points, axis=1).ravel()
    return np.array(
        [
            points[sums.argmin()],
            points[diffs.argmin()],
            points[sums.argmax()],
            points[diffs.argmax()],
        ],
        dtype=np.float32,
    )


def flatten_page(rgb: np.ndarray) -> np.ndarray:
    """Warp the sheet of paper to a straight rectangle, or return the photo as it is
    when no sheet stands out from the background."""
    height, width = rgb.shape[:2]
    scale = 1000 / max(height, width)
    small = cv2.resize(rgb, None, fx=scale, fy=scale)
    gray = cv2.GaussianBlur(cv2.cvtColor(small, cv2.COLOR_RGB2GRAY), (5, 5), 0)
    _, mask = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((15, 15), np.uint8))
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return rgb
    paper = max(contours, key=cv2.contourArea)
    if cv2.contourArea(paper) < MIN_PAGE_AREA * small.shape[0] * small.shape[1]:
        return rgb
    quad = cv2.approxPolyDP(paper, 0.02 * cv2.arcLength(paper, True), True)
    if len(quad) != 4:
        quad = cv2.boxPoints(cv2.minAreaRect(paper))
    corners = _corners(quad.reshape(-1, 2).astype(np.float32) / scale)
    tl, tr, br, bl = corners
    out_w = int(max(np.linalg.norm(tr - tl), np.linalg.norm(br - bl)))
    out_h = int(max(np.linalg.norm(bl - tl), np.linalg.norm(br - tr)))
    target = np.array(
        [[0, 0], [out_w - 1, 0], [out_w - 1, out_h - 1], [0, out_h - 1]],
        dtype=np.float32,
    )
    matrix = cv2.getPerspectiveTransform(corners, target)
    return cv2.warpPerspective(rgb, matrix, (out_w, out_h), flags=cv2.INTER_CUBIC)


def _shrink(rgb: np.ndarray) -> np.ndarray:
    scale = MAX_PAGE_SIDE / max(rgb.shape[:2])
    if scale >= 1:
        return rgb
    return cv2.resize(rgb, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)


def _contrast(rgb: np.ndarray) -> np.ndarray:
    lightness, a, b = cv2.split(cv2.cvtColor(rgb, cv2.COLOR_RGB2LAB))
    lightness = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(lightness)
    return cv2.cvtColor(cv2.merge((lightness, a, b)), cv2.COLOR_LAB2RGB)


def clean_photo(data: bytes) -> np.ndarray:
    photo = ImageOps.exif_transpose(Image.open(io.BytesIO(data))).convert("RGB")
    return _contrast(_shrink(flatten_page(np.asarray(photo))))


def ingest_photo(data: bytes, out_dir: str | Path) -> IngestResult:
    """A photo is one page: cleaned, saved as <hash>-p1.png in out_dir, then read."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    file_hash = sha256_hex(data)

    page = clean_photo(data)
    img_path = out / f"{file_hash}-p1.png"
    Image.fromarray(page).save(img_path)
    height, width = page.shape[:2]
    return IngestResult(
        file_hash=file_hash,
        pages=[
            Page(
                number=1,
                width=width,
                height=height,
                image_path=str(img_path),
                lines=_read_lines(page, 1),
                needs_ocr=True,
            )
        ],
    )


def read_scanned_pages(result: IngestResult) -> IngestResult:
    """OCR the PDF pages that have no text layer. Their rendered page images stay as
    they are: a scan is already page-shaped."""
    pages = [
        page.model_copy(
            update={
                "lines": _read_lines(
                    np.asarray(Image.open(page.image_path).convert("RGB")),
                    page.number,
                )
            }
        )
        if page.needs_ocr
        else page
        for page in result.pages
    ]
    return result.model_copy(update={"pages": pages})

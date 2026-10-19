"""api/app/pipeline/ingest.py

Step 1 of the OneChart pipeline: digital PDF -> numbered lines with boxes + page PNGs.
(Pages with no text layer are flagged with needs_ocr and read by ocr.py.)

Bounding boxes are returned in IMAGE PIXELS at RENDER_DPI, so the source viewer can draw
highlights directly on the page PNG without any extra scaling.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pymupdf as fitz
from pydantic import BaseModel

RENDER_DPI = 150
PDF_POINTS_PER_INCH = 72
SCALE = RENDER_DPI / PDF_POINTS_PER_INCH
MIN_TEXT_CHARS = 20  # fewer chars than this on a page => treat as no text layer


# --- Models (move to api/app/pipeline/schemas.py when that file exists) -----------------
class Line(BaseModel):
    id: str  # e.g. "p1-L12"
    page: int  # 1-based
    text: str
    bbox: list[float]  # [x0, y0, x1, y1] in image pixels


class Page(BaseModel):
    number: int  # 1-based
    width: int  # image width in px
    height: int  # image height in px
    image_path: str
    lines: list[Line]
    needs_ocr: bool


class IngestResult(BaseModel):
    file_hash: str
    pages: list[Page]


# --- Helpers ---------------------------------------------------------------------------
def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _page_lines(page: fitz.Page, page_no: int) -> list[Line]:
    """Read the text layer line by line, numbering lines sequentially per page."""
    lines: list[Line] = []
    n = 0
    for block in page.get_text("dict", sort=True)["blocks"]:
        if block["type"] != 0:  # skip image blocks
            continue
        for ln in block["lines"]:
            text = "".join(span["text"] for span in ln["spans"]).strip()
            if not text:
                continue
            n += 1
            x0, y0, x1, y1 = (v * SCALE for v in ln["bbox"])
            lines.append(
                Line(
                    id=f"p{page_no}-L{n}",
                    page=page_no,
                    text=text,
                    bbox=[round(x0, 1), round(y0, 1), round(x1, 1), round(y1, 1)],
                )
            )
    return lines


# --- Public API ------------------------------------------------------------------------
def ingest_pdf(data: bytes, out_dir: str | Path) -> IngestResult:
    """Ingest a PDF given as bytes.

    Writes one PNG per page to out_dir (named <hash>-p<N>.png) and returns the numbered
    lines. Same file bytes -> same hash -> same line ids, which keeps Gemini's evidence
    citations stable and lets callers cache by hash.
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    file_hash = sha256_hex(data)
    pages: list[Page] = []

    with fitz.open(stream=data, filetype="pdf") as doc:
        for page_no, page in enumerate(doc, start=1):
            lines = _page_lines(page, page_no)

            pix = page.get_pixmap(dpi=RENDER_DPI)
            img_path = out / f"{file_hash}-p{page_no}.png"
            pix.save(str(img_path))

            total_chars = sum(len(l.text) for l in lines)
            pages.append(
                Page(
                    number=page_no,
                    width=pix.width,
                    height=pix.height,
                    image_path=str(img_path),
                    lines=lines,
                    needs_ocr=total_chars < MIN_TEXT_CHARS,
                )
            )

    return IngestResult(file_hash=file_hash, pages=pages)


def ingest_pdf_path(path: str | Path, out_dir: str | Path) -> IngestResult:
    return ingest_pdf(Path(path).read_bytes(), out_dir)


def format_for_prompt(result: IngestResult) -> str:
    """Numbered lines in the form Gemini sees: '[p1-L12] Metformin 500 mg twice daily'."""
    return "\n".join(f"[{l.id}] {l.text}" for p in result.pages for l in p.lines)


# --- Debug CLI: python ingest.py file.pdf  -> prints lines, writes boxed PNGs ------------
if __name__ == "__main__":
    import sys

    from PIL import Image, ImageDraw

    if len(sys.argv) < 2:
        sys.exit("usage: python ingest.py file.pdf [out_dir]")

    out_dir = sys.argv[2] if len(sys.argv) > 2 else "ingest_out"
    res = ingest_pdf_path(sys.argv[1], out_dir)
    print(format_for_prompt(res))

    for p in res.pages:
        img = Image.open(p.image_path).convert("RGB")
        draw = ImageDraw.Draw(img)
        for l in p.lines:
            draw.rectangle(l.bbox, outline="red", width=2)
        img.save(Path(out_dir) / f"{res.file_hash}-p{p.number}-boxed.png")
        print(f"page {p.number}: {len(p.lines)} lines, needs_ocr={p.needs_ocr}")

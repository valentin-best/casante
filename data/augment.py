"""augment.py: turn clean PDFs into fake "phone photo" versions to test the OCR path.

Usage (from the repo root):
    python data/augment.py --pdf-dir data/synthea/pdfs --out-dir data/synthea/photos
    python data/augment.py --pdf-dir data/synthea/pdfs --out-dir data/synthea/photos --variants 2 --seed 7

Install:
    pip install albumentations opencv-python-headless pymupdf numpy

What it does to every page of every PDF:
    1. Render the page at 150 dpi (same as the source viewer).
    2. Put it on a darker "table" background with random margins, like a real photo.
    3. Albumentations pipeline:
         - rotation up to 7 degrees
         - perspective warp (camera not held straight)
         - blur (gaussian or motion, sometimes none)
         - brightness / contrast shifts, plus an occasional shadow
    4. Save as JPEG with random quality 40-70 (this is the compression step).

Output: <out-dir>/<pdf stem>_p<N>_v<K>.jpg and a manifest.json with the
parameters used, so any failure case in the README can be reproduced.
"""

import argparse
import json
import random
from pathlib import Path

import albumentations as A
import cv2
import pymupdf
import numpy as np


def render_pages(pdf_path: Path, dpi: int = 150):
    """Yield (page_number, RGB uint8 array) for each page."""
    with pymupdf.open(pdf_path) as doc:
        for i, page in enumerate(doc, start=1):
            pix = page.get_pixmap(dpi=dpi, colorspace=pymupdf.csRGB, alpha=False)
            img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(
                pix.height, pix.width, 3
            )
            yield i, img.copy()


def put_on_table(img: np.ndarray, rng: random.Random) -> np.ndarray:
    """Place the page on a wood/desk-like background with uneven margins."""
    h, w = img.shape[:2]
    top, bottom = (int(h * rng.uniform(0.03, 0.10)) for _ in range(2))
    left, right = (int(w * rng.uniform(0.03, 0.10)) for _ in range(2))
    base = np.array(
        [rng.randint(60, 130), rng.randint(45, 100), rng.randint(30, 80)],
        dtype=np.uint8,
    )
    canvas = np.empty((h + top + bottom, w + left + right, 3), dtype=np.uint8)
    canvas[:] = base
    noise = np.random.default_rng(rng.randint(0, 2**31)).integers(
        -12, 12, canvas.shape, dtype=np.int16
    )
    canvas = np.clip(canvas.astype(np.int16) + noise, 0, 255).astype(np.uint8)
    canvas[top : top + h, left : left + w] = img
    return canvas


def build_pipeline(seed: int) -> A.Compose:
    blur = A.OneOf(
        [
            A.GaussianBlur(blur_limit=(3, 7), p=1.0),
            A.MotionBlur(blur_limit=(3, 9), p=1.0),
        ],
        p=0.7,  # 30% of photos stay sharp
    )
    return A.Compose(
        [
            A.Rotate(limit=7, border_mode=cv2.BORDER_REPLICATE, p=1.0),
            A.Perspective(
                scale=(0.02, 0.06),
                keep_size=True,
                border_mode=cv2.BORDER_REPLICATE,
                p=0.9,
            ),
            blur,
            A.RandomBrightnessContrast(
                brightness_limit=(-0.3, 0.25), contrast_limit=(-0.2, 0.2), p=1.0
            ),
            A.RandomShadow(p=0.4),
            A.GaussNoise(p=0.3),
        ],
        seed=seed,
    )


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--pdf-dir", required=True, type=Path)
    ap.add_argument("--out-dir", required=True, type=Path)
    ap.add_argument("--variants", type=int, default=1, help="photo versions per page")
    ap.add_argument("--dpi", type=int, default=150)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--quality-min", type=int, default=40)
    ap.add_argument("--quality-max", type=int, default=70)
    args = ap.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)
    pdfs = sorted(args.pdf_dir.rglob("*.pdf"))
    if not pdfs:
        raise SystemExit(f"No PDFs found in {args.pdf_dir}")

    manifest = []
    for pdf in pdfs:
        # Unique id from the path under pdf-dir, e.g. patient_03__lab_report
        doc_id = "__".join(pdf.relative_to(args.pdf_dir).with_suffix("").parts)
        for page_no, page_img in render_pages(pdf, args.dpi):
            for v in range(args.variants):
                # Deterministic per (file, page, variant) so reruns give identical photos
                key = f"{args.seed}:{doc_id}:{page_no}:{v}"
                rng = random.Random(key)
                quality = rng.randint(args.quality_min, args.quality_max)

                staged = put_on_table(page_img, rng)
                out = build_pipeline(rng.randint(0, 2**31 - 1))(image=staged)["image"]

                name = f"{doc_id}_p{page_no}_v{v}.jpg"
                bgr = cv2.cvtColor(out, cv2.COLOR_RGB2BGR)
                cv2.imwrite(
                    str(args.out_dir / name), bgr, [cv2.IMWRITE_JPEG_QUALITY, quality]
                )
                manifest.append(
                    {
                        "file": name,
                        "source_pdf": str(pdf.relative_to(args.pdf_dir)),
                        "page": page_no,
                        "variant": v,
                        "jpeg_quality": quality,
                        "seed_key": key,
                    }
                )

    (args.out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(f"Wrote {len(manifest)} photos from {len(pdfs)} PDFs to {args.out_dir}")


if __name__ == "__main__":
    main()

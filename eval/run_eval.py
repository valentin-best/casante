"""run_eval.py: score the extraction pipeline against Synthea ground truth.

    cd api && uv run --env-file .env --with matplotlib python ../eval/run_eval.py   # real pipeline
    python eval/run_eval.py --mock         # fake pipeline, to test scoring + chart
    python eval/run_eval.py --limit 6      # smoke test on the first 6 documents
    python eval/run_eval.py --conditions clean
    python eval/run_eval.py --cached-only  # re-score cached documents only, no model calls

Install: pip install matplotlib

What it does
    * Runs every document twice: as the clean PDF and as the phone-photo version
      made by data/augment.py (variant 0 by default).
    * Scores medications (RxCUI + dose), allergies (substance), conditions (name)
      and labs (LOINC, value within 1%): precision, recall, F1 per field.
    * Checks recall on planted conflicts by running reconcile per patient.
    * Records average seconds per document.
    * Runs in small batches with a pause between batches and exponential backoff
      on errors. Each finished document is cached in results/cache/, so a crash
      or rate limit never loses work: rerun and it resumes. Use --no-cache to redo.

Ground truth: one data/pdfs/<patient>/ground_truth.json per patient (written by
render.py), merged on load. Document ids are "<patient folder>__<document>", for
example p01__lab_report, the same ids augment.py uses in photo filenames.
Planted conflicts are matched against what reconcile reports:
    dose_conflict           key = rxcui
    allergy_only_in_oldest  key = allergy substance

Outputs (in eval/results/): metrics.json, metrics.md (README table), failures.json
(every missed or extra item, for the README failure cases), chart.png.
"""

import argparse
import json
import random
import re
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from types import SimpleNamespace

REPO_ROOT = Path(__file__).resolve().parents[1]
FIELDS = ["medications", "allergies", "conditions", "labs"]
FIELD_LABELS = {
    "medications": "Medications",
    "allergies": "Allergies",
    "conditions": "Conditions",
    "labs": "Labs",
}
CONDITIONS = {"clean": "Clean PDF", "photo": "Phone photo"}


# ----------------------------------------------------------------------------
# Normalization and matching
# ----------------------------------------------------------------------------
def norm_text(s):
    return re.sub(r"\s+", " ", str(s or "").strip().lower())


def code_of(item, *names):
    for n in (*names, "code"):
        v = item.get(n)
        if v not in (None, ""):
            return str(v).strip().lower()
    return None


DOSE_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(mcg|µg|ug|mg|g|ml|iu|units?|%)", re.I)


def parse_dose(s):
    """'500 mg' -> (500.0, 'mg'); 'Metformin 0.5 g' -> (500.0, 'mg'); None -> None."""
    if s in (None, ""):
        return None
    m = DOSE_RE.search(str(s))
    if not m:
        return norm_text(s)
    val, unit = float(m.group(1)), m.group(2).lower()
    unit = (
        "mcg" if unit in ("µg", "ug") else "unit" if unit.startswith("unit") else unit
    )
    if unit == "g":
        val, unit = val * 1000, "mg"
    return (round(val, 4), unit)


def eq_med(g, p):
    gc, pc = code_of(g, "rxcui"), code_of(p, "rxcui")
    gn, pn = norm_text(g.get("name")), norm_text(p.get("name"))
    # RxNav may resolve a printed name to a different RxCUI than Synthea's, so a name
    # match counts too. Synthea names carry strength and form ("Clopidogrel 75 MG Oral
    # Tablet") where the extraction often splits them out, so a shorter name inside the
    # longer one is the same drug.
    same_drug = (
        bool(gc and gc == pc)
        or gn == pn
        or bool(pn and pn in gn)
        or bool(gn and gn in pn)
    )
    # Synthea often leaves dose empty and keeps it in the name
    return same_drug and parse_dose(g.get("dose") or g.get("name")) == parse_dose(
        p.get("dose") or p.get("name")
    )


def eq_allergy(g, p):
    return norm_text(g.get("substance")) == norm_text(p.get("substance"))


def eq_condition(g, p):
    return norm_text(g.get("name")) == norm_text(p.get("name"))


def eq_lab(g, p):
    gc, pc = code_of(g, "loinc"), code_of(p, "loinc")
    gn, pn = g.get("test") or g.get("name"), p.get("test") or p.get("name")
    # The API maps blood and serum variants to one LOINC on purpose, so a name match counts too
    same = bool(gc and gc == pc) or norm_text(gn) == norm_text(pn)
    if not same:
        return False
    try:
        gv, pv = float(g["value"]), float(p["value"])
    except (KeyError, TypeError, ValueError):
        return False
    return abs(pv - gv) <= 0.01 * abs(gv)  # within 1%


EQ = {
    "medications": eq_med,
    "allergies": eq_allergy,
    "conditions": eq_condition,
    "labs": eq_lab,
}


def match(gt, pred, eq):
    """Greedy one-to-one matching. Returns (true positives, extra predictions, missed truths)."""
    used, tp, missed = set(), 0, []
    for g in gt:
        for j, p in enumerate(pred):
            if j not in used and eq(g, p):
                used.add(j)
                tp += 1
                break
        else:
            missed.append(g)
    extra = [p for j, p in enumerate(pred) if j not in used]
    return tp, extra, missed


def prf(tp, fp, fn):
    p = tp / (tp + fp) if (tp + fp) else (1.0 if fn == 0 else 0.0)
    r = tp / (tp + fn) if (tp + fn) else 1.0
    f1 = 2 * p * r / (p + r) if (p + r) else 0.0
    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "precision": round(p, 4),
        "recall": round(r, 4),
        "f1": round(f1, 4),
    }


# ----------------------------------------------------------------------------
# Pipelines
# ----------------------------------------------------------------------------
class RealPipeline:
    """Runs the API's own pipeline: ingest (+ OCR), Gemini extraction, normalize, reconcile.

    Run it with the API's environment, from api/ so the Gemini and RxNav caches are shared:
        cd api && uv run --env-file .env --with matplotlib python ../eval/run_eval.py
    """

    def __init__(self):
        sys.path.insert(0, str(REPO_ROOT / "api"))
        from app.pipeline import extract, ingest, ocr  # type: ignore
        from app.record import build_record  # type: ignore

        self.m = SimpleNamespace(extract=extract, ingest=ingest, ocr=ocr)
        self.build_record = build_record

    def _extract(self, path):
        import tempfile

        data = Path(path).read_bytes()
        with tempfile.TemporaryDirectory() as tmp:
            if Path(path).suffix.lower() == ".pdf":
                ingested = self.m.ocr.read_scanned_pages(
                    self.m.ingest.ingest_pdf(data, tmp)
                )
            else:
                ingested = self.m.ocr.ingest_photo(data, tmp)
            return self.m.extract.extract_document(ingested).model_dump(mode="json")

    def process(self, doc_id, paths, condition):
        """One extraction per file. A multi-page photo document merges its pages."""
        pages = [self._extract(path) for path in paths]
        extraction = {"document": pages[0]["document"]}
        for f in (*FIELDS, "procedures"):
            extraction[f] = [item for page in pages for item in page.get(f, [])]
        # Normalize the same way GET /record does, one document at a time
        record = self.build_record(
            [{"id": doc_id, "filename": doc_id, "extraction": extraction}]
        )
        return {
            "extraction": extraction,
            "medications": [
                {
                    "name": m["name"],
                    "dose": m.get("dose"),
                    "rxcui": m["normalized"]["rxcui"],
                }
                for m in record["medications"]
            ],
            "allergies": [{"substance": a["substance"]} for a in record["allergies"]],
            "conditions": [{"name": c["name"]} for c in record["conditions"]],
            "labs": [
                {
                    "test": lab["test"],
                    "value": lab.get("value"),
                    "loinc": lab["normalized"]["loinc"],
                }
                for lab in record["labs"]
            ],
        }

    def reconcile(self, items_by_doc):
        """Conflicts from the real record, keyed every way a planted conflict may name them."""
        record = self.build_record(
            [
                {"id": doc_id, "filename": doc_id, "extraction": items["extraction"]}
                for doc_id, items in items_by_doc.items()
                if "extraction" in items  # failed documents have none
            ]
        )
        by_source = defaultdict(list)  # (section, document id) -> items
        for section in ("medications", "allergies"):
            for item in record[section]:
                for source in item["sources"]:
                    by_source[section, source["document_id"]].append(item)
        out = []
        for c in record["conflicts"]:
            kind = {"dose": "dose", "allergy_missing": "allergy"}.get(c["kind"])
            if kind is None:
                continue
            keys = {c["key"], c["name"]}
            for variant in c["variants"]:
                for source in variant["sources"]:
                    for item in by_source[c["section"], source["document_id"]]:
                        if item["normalized"]["key"] == c["key"]:
                            keys.add(item["normalized"].get("rxcui") or "")
                            keys.add(item.get("name") or item.get("substance") or "")
            out += [{"type": kind, "key": k} for k in keys if k]
        return out


def simple_reconcile(items_by_doc):
    """Minimal stand-in for reconcile.py. Mock mode only."""
    doses, allergy_docs = defaultdict(set), defaultdict(set)
    for doc_id, items in items_by_doc.items():
        for m in items.get("medications", []):
            doses[code_of(m, "rxcui") or norm_text(m.get("name"))].add(
                parse_dose(m.get("dose"))
            )
        for a in items.get("allergies", []):
            allergy_docs[norm_text(a.get("substance"))].add(doc_id)
    out = [{"type": "dose", "key": k} for k, d in doses.items() if len(d) > 1]
    out += [
        {"type": "allergy", "key": k}
        for k, docs in allergy_docs.items()
        if len(docs) < len(items_by_doc)
    ]
    return out


class MockPipeline:
    """Ground truth with random damage. Only for testing the scoring, report and chart."""

    def __init__(self, gt_docs, seed):
        self.gt, self.seed = gt_docs, seed

    def process(self, doc_id, paths, condition):
        rng = random.Random(f"{self.seed}:{doc_id}:{condition}")
        p_err = 0.05 if condition == "clean" else 0.15
        out = {f: [] for f in FIELDS}
        for f in FIELDS:
            for item in self.gt[doc_id].get(f) or []:
                if rng.random() < p_err:
                    continue  # missed
                item = dict(item)
                if f == "medications" and item.get("dose") and rng.random() < p_err / 2:
                    item["dose"] = re.sub(
                        r"\d+", lambda m: m.group(0) + "0", item["dose"], count=1
                    )
                out[f].append(item)
        return out

    def reconcile(self, items_by_doc):
        return simple_reconcile(items_by_doc)


# ----------------------------------------------------------------------------
# Loading documents
# ----------------------------------------------------------------------------
# planted conflict type in ground_truth.json -> (type reconcile should report, key field)
CONFLICT_TYPES = {
    "dose_conflict": ("dose", "rxcui"),
    "allergy_only_in_oldest": ("allergy", "allergy"),
}


def load_ground_truth(pdf_dir, path=None):
    """Merge per-patient ground_truth.json files into {doc_id: items} + planted conflicts.

    path may be a single file, a folder of patient folders, or None (use pdf_dir).
    """
    path = Path(path) if path else Path(pdf_dir)
    files = [path] if path.is_file() else sorted(path.glob("*/ground_truth.json"))
    if not files:
        raise SystemExit(f"No ground_truth.json files found under {path}")
    docs, planted = {}, []
    for f in files:
        raw = json.loads(f.read_text())
        pid = f.parent.name  # matches the folder name used in photo and pdf ids
        for name, doc in raw["documents"].items():
            docs[f"{pid}__{name}"] = {**doc, "patient": pid}
        for c in raw.get("planted_conflicts", []):
            kind = CONFLICT_TYPES.get(c["type"])
            if kind is None:
                print(
                    f"warning: unknown planted conflict type {c['type']!r} in {f}, skipped"
                )
                continue
            planted.append({"patient": pid, "type": kind[0], "key": str(c[kind[1]])})
    return docs, planted


def find_pdf_docs(pdf_dir):
    return {
        "__".join(p.relative_to(pdf_dir).with_suffix("").parts): [p]
        for p in sorted(pdf_dir.rglob("*.pdf"))
    }


PHOTO_RE = re.compile(r"^(?P<doc>.+)_p(?P<page>\d+)_v(?P<var>\d+)\.jpe?g$", re.I)


def find_photo_docs(photo_dir, variant):
    docs = defaultdict(list)
    for f in sorted(photo_dir.glob("*.jp*g")):
        m = PHOTO_RE.match(f.name)
        if m and int(m["var"]) == variant:
            docs[m["doc"]].append((int(m["page"]), f))
    return {d: [p for _, p in sorted(v)] for d, v in docs.items()}


# ----------------------------------------------------------------------------
# Running with batches, backoff and a resume cache
# ----------------------------------------------------------------------------
def run_with_backoff(fn, retries, base=2.0):
    """Returns (result, seconds, error). Only the successful attempt is timed."""
    for attempt in range(retries + 1):
        t0 = time.perf_counter()
        try:
            return fn(), time.perf_counter() - t0, None
        except Exception as e:  # noqa: BLE001
            err = f"{type(e).__name__}: {e}"
            if attempt == retries:
                return None, 0.0, err
            wait = base * 2**attempt + random.random()
            print(f"    error ({err[:90]}); retrying in {wait:.0f}s")
            time.sleep(wait)


def run_condition(pipe, condition, docs, cache_dir, args):
    cache_dir.mkdir(parents=True, exist_ok=True)
    results, pending = {}, []
    for doc_id, paths in docs.items():
        cf = cache_dir / f"{doc_id}.json"
        if cf.exists() and not args.no_cache:
            results[doc_id] = json.loads(cf.read_text())
        else:
            pending.append((doc_id, paths))
    print(
        f"[{condition}] {len(docs)} documents, {len(results)} cached, {len(pending)} to run"
    )

    done = 0
    for i in range(0, len(pending), args.batch_size):
        for doc_id, paths in pending[i : i + args.batch_size]:
            items, secs, err = run_with_backoff(
                lambda: pipe.process(doc_id, paths, condition), args.retries
            )
            rec = {
                "items": items or {f: [] for f in FIELDS},
                "seconds": secs,
                "error": err,
            }
            results[doc_id] = rec
            if err is None:  # failed docs are not cached, so a rerun retries them
                (cache_dir / f"{doc_id}.json").write_text(json.dumps(rec))
            done += 1
            print(
                f"  [{condition} {done}/{len(pending)}] {doc_id}  "
                f"{'FAILED: ' + err[:80] if err else f'{secs:.1f}s'}"
            )
        if i + args.batch_size < len(pending):
            time.sleep(args.batch_pause)
    return results


# ----------------------------------------------------------------------------
# Scoring
# ----------------------------------------------------------------------------
def score_condition(gt_docs, results):
    counts = {f: Counter() for f in FIELDS}
    failures = []
    for doc_id, r in results.items():
        gt = gt_docs[doc_id]
        for f in FIELDS:
            tp, extra, missed = match(gt.get(f) or [], r["items"].get(f) or [], EQ[f])
            counts[f]["tp"] += tp
            counts[f]["fp"] += len(extra)
            counts[f]["fn"] += len(missed)
            for g in missed:
                failures.append(
                    {
                        "doc_id": doc_id,
                        "field": f,
                        "kind": "missed",
                        "expected": g,
                        "doc_error": r.get("error"),
                    }
                )
            for p in extra:
                failures.append(
                    {"doc_id": doc_id, "field": f, "kind": "extra", "got": p}
                )
    return counts, failures


def score_conflicts(pipe, planted, gt_docs, results):
    by_patient = defaultdict(dict)
    for doc_id, r in results.items():
        by_patient[gt_docs[doc_id]["patient"]][doc_id] = r["items"]
    predicted, found, total, detail = {}, 0, 0, []
    for c in planted:
        pat = c["patient"]
        if pat not in by_patient:
            detail.append(
                {**c, "detected": None, "note": "no documents for this patient"}
            )
            continue
        # A conflict spans documents, so it can't be found from part of them (--cached-only)
        if any(g["patient"] == pat and d not in results for d, g in gt_docs.items()):
            detail.append({**c, "detected": None, "note": "not all documents scored"})
            continue
        if pat not in predicted:
            try:
                predicted[pat] = {
                    (x["type"], norm_text(x["key"]))
                    for x in pipe.reconcile(by_patient[pat])
                }
            except Exception as e:  # noqa: BLE001
                print(f"  reconcile failed for {pat}: {e}")
                predicted[pat] = set()
        hit = (c["type"], norm_text(c["key"])) in predicted[pat]
        total += 1
        found += hit
        detail.append({**c, "detected": hit})
    return {
        "found": found,
        "total": total,
        "recall": round(found / total, 4) if total else None,
        "detail": detail,
    }


# ----------------------------------------------------------------------------
# Reporting
# ----------------------------------------------------------------------------
def fmt(x):
    return "n/a" if x is None else f"{x:.2f}"


def write_markdown(metrics, path):
    def f1(cond, f):
        return metrics.get(cond, {}).get("fields", {}).get(f, {}).get("f1")

    def rec(cond):
        return (metrics.get(cond, {}).get("conflicts") or {}).get("recall")

    lines = ["| Field | Clean PDF F1 | Photo F1 |", "|---|---|---|"]
    for f in FIELDS:
        lines.append(
            f"| {FIELD_LABELS[f]} | {fmt(f1('clean', f))} | {fmt(f1('photo', f))} |"
        )
    lines.append(
        f"| Planted conflicts found (recall) | {fmt(rec('clean'))} | {fmt(rec('photo'))} |"
    )
    lines += [
        "",
        "| Condition | Field | Precision | Recall | F1 | TP | FP | FN |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for cond in ("clean", "photo"):
        for f, m in metrics.get(cond, {}).get("fields", {}).items():
            lines.append(
                f"| {CONDITIONS[cond]} | {FIELD_LABELS[f]} | {m['precision']:.2f} | "
                f"{m['recall']:.2f} | {m['f1']:.2f} | {m['tp']} | {m['fp']} | {m['fn']} |"
            )
    lines += [
        "",
        "| Condition | Documents | Failed | Avg seconds per document |",
        "|---|---|---|---|",
    ]
    for cond in ("clean", "photo"):
        if cond in metrics:
            m = metrics[cond]
            lines.append(
                f"| {CONDITIONS[cond]} | {m['n_docs']} | {m['failed_docs']} | "
                f"{m['avg_seconds_per_doc']:.1f} |"
            )
    path.write_text("\n".join(lines) + "\n")


def make_chart(metrics, path):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    labels = [FIELD_LABELS[f] for f in FIELDS] + ["Planted conflicts\n(recall)"]
    conds = [c for c in ("clean", "photo") if c in metrics]
    fig, ax = plt.subplots(figsize=(8, 4.5))
    width = 0.8 / max(len(conds), 1)
    for i, cond in enumerate(conds):
        vals = [metrics[cond]["fields"][f]["f1"] for f in FIELDS]
        vals.append((metrics[cond].get("conflicts") or {}).get("recall") or 0.0)
        offset = (i - (len(conds) - 1) / 2) * width
        bars = ax.bar(
            [x + offset for x in range(len(labels))],
            vals,
            width,
            label=CONDITIONS[cond],
        )
        ax.bar_label(bars, fmt="%.2f", padding=2, fontsize=8)
    ax.set_xticks(range(len(labels)))
    ax.set_xticklabels(labels)
    ax.set_ylim(0, 1.12)
    ax.set_ylabel("F1 (conflicts: recall)")
    ax.set_title("CaSanté extraction quality vs Synthea ground truth")
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.16), ncol=2, frameon=False)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


# ----------------------------------------------------------------------------
def main():
    here = Path(__file__).resolve().parent
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    default_photos = next(
        (
            d
            for d in (REPO_ROOT / "data/photos", REPO_ROOT / "data/synthea/photos")
            if d.exists()
        ),
        REPO_ROOT / "data/photos",
    )
    ap.add_argument("--pdf-dir", type=Path, default=REPO_ROOT / "data/pdfs")
    ap.add_argument("--photo-dir", type=Path, default=default_photos)
    ap.add_argument(
        "--ground-truth",
        type=Path,
        help="a single file or a folder of patient folders (default: --pdf-dir)",
    )
    ap.add_argument("--out-dir", type=Path, default=here / "results")
    ap.add_argument(
        "--conditions", nargs="+", choices=list(CONDITIONS), default=list(CONDITIONS)
    )
    ap.add_argument(
        "--variant", type=int, default=0, help="which photo variant to score"
    )
    ap.add_argument("--limit", type=int, help="only the first N documents (smoke test)")
    ap.add_argument("--batch-size", type=int, default=5)
    ap.add_argument(
        "--batch-pause", type=float, default=10.0, help="seconds between batches"
    )
    ap.add_argument(
        "--retries",
        type=int,
        default=4,
        help="retries per document, backoff 2s, 4s, 8s...",
    )
    ap.add_argument(
        "--no-cache", action="store_true", help="ignore cached results and rerun"
    )
    ap.add_argument(
        "--cached-only",
        action="store_true",
        help="score only documents already in the cache (no model calls)",
    )
    ap.add_argument(
        "--mock", action="store_true", help="fake pipeline to test scoring and chart"
    )
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    gt_docs, planted = load_ground_truth(args.pdf_dir, args.ground_truth)
    if args.limit:
        gt_docs = {k: gt_docs[k] for k in sorted(gt_docs)[: args.limit]}
    if not planted:
        print(
            "Note: no planted_conflicts in the ground truth, so conflict recall is skipped."
        )

    out_dir = args.out_dir / "mock" if args.mock else args.out_dir
    cache_root = out_dir / "cache"
    out_dir.mkdir(parents=True, exist_ok=True)
    pipe = MockPipeline(gt_docs, args.seed) if args.mock else RealPipeline()

    metrics = {
        "config": {
            "mock": args.mock,
            "variant": args.variant,
            "limit": args.limit,
            "cached_only": args.cached_only,
            "batch_size": args.batch_size,
            "seed": args.seed,
        }
    }
    all_failures = {}
    for cond in args.conditions:
        found = (
            find_pdf_docs(args.pdf_dir)
            if cond == "clean"
            else find_photo_docs(args.photo_dir, args.variant)
        )
        docs = {d: found[d] for d in gt_docs if d in found}
        if len(docs) < len(gt_docs):
            print(
                f"[{cond}] warning: {len(gt_docs) - len(docs)} ground-truth documents have no file"
            )
        if args.cached_only:
            docs = {
                d: p
                for d, p in docs.items()
                if (cache_root / cond / f"{d}.json").exists()
            }
        if not docs:
            print(f"[{cond}] nothing to evaluate, skipping")
            continue
        results = run_condition(pipe, cond, docs, cache_root / cond, args)
        counts, failures = score_condition(gt_docs, results)
        secs = [r["seconds"] for r in results.values() if not r["error"]]
        metrics[cond] = {
            "n_docs": len(results),
            "failed_docs": sum(1 for r in results.values() if r["error"]),
            "avg_seconds_per_doc": round(sum(secs) / len(secs), 2) if secs else 0.0,
            "fields": {f: prf(c["tp"], c["fp"], c["fn"]) for f, c in counts.items()},
            "conflicts": score_conflicts(pipe, planted, gt_docs, results)
            if planted
            else None,
        }
        all_failures[cond] = failures

    (out_dir / "metrics.json").write_text(json.dumps(metrics, indent=2))
    (out_dir / "failures.json").write_text(json.dumps(all_failures, indent=2))
    write_markdown(metrics, out_dir / "metrics.md")
    if any(c in metrics for c in CONDITIONS):
        make_chart(metrics, out_dir / "chart.png")
    print("\n" + (out_dir / "metrics.md").read_text())
    print(f"Saved metrics.json, metrics.md, failures.json, chart.png to {out_dir}")


if __name__ == "__main__":
    main()

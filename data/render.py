#!/usr/bin/env python3
"""Turn Synthea FHIR bundles into synthetic clinical PDFs + ground truth.

    python data/render.py                      # all bundles in data/fhir -> data/out
    python data/render.py --fhir PATH --out PATH --seed 42 --conflicts 5

Per patient (out/p01, p02, ...): discharge_summary.pdf, clinic_letter.pdf,
lab_report.pdf and ground_truth.json (exactly what is printed + planted conflicts).
"""
import argparse
import json
import random
import re
from collections import OrderedDict
from datetime import datetime, timedelta
from pathlib import Path

from jinja2 import Environment, FileSystemLoader
from weasyprint import HTML

HERE = Path(__file__).parent
DOC_TYPES = ["discharge_summary", "clinic_letter", "lab_report"]

# ---- fictional clinic identities / styles (varied so 3 docs look like 3 clinics) ----
FACILITIES = [
    ("Riverside General Hospital", "12 Harbor Road"), ("Maple Grove Family Clinic", "48 Maple Avenue"),
    ("St. Anselm Medical Center", "300 Cathedral Street"), ("Northgate Internal Medicine", "9 Northgate Plaza"),
    ("Cedar Valley Health Partners", "77 Cedar Lane"), ("Lakeshore Diagnostics", "5 Lakeshore Drive"),
    ("Bayview Community Hospital", "210 Bay Street"), ("Oakwood Specialty Clinic", "63 Oakwood Court"),
    ("Summit Regional Laboratory", "1 Summit Park"), ("Pinecrest Medical Group", "88 Pinecrest Road"),
    ("Willow Creek Physicians", "21 Willow Creek Way"), ("Harborview Pathology Services", "14 Dockside Row"),
]
DOCTORS = ["Dr. A. Patel", "Dr. M. Okafor", "Dr. L. Nguyen", "Dr. S. Johansson", "Dr. R. Fernandez",
           "Dr. K. Tanaka", "Dr. E. Rossi", "Dr. J. Williams", "Dr. H. Kim", "Dr. C. Dubois", "Dr. T. Alvarez"]
STYLES = [
    {"font": "'DejaVu Serif', serif", "size": 10.5}, {"font": "'Inter', 'DejaVu Sans', sans-serif", "size": 10},
    {"font": "'Carlito', 'DejaVu Sans', sans-serif", "size": 11}, {"font": "'FreeSerif', serif", "size": 11},
    {"font": "'DejaVu Sans Mono', monospace", "size": 9}, {"font": "'Bitstream Charter', serif", "size": 10.5},
]
ACCENTS = ["#0b5394", "#7a1f3d", "#1b6b4a", "#4a3b8c", "#8a4b08", "#1f4f5f", "#333333"]

FREQS = ["once daily", "twice daily", "three times daily", "at bedtime", "every 12 hours"]
# synthetic fallbacks so every conflict patient has a doseable medication (real RxNorm codes)
FALLBACK_MEDS = [
    ("861007", "Metformin hydrochloride 500 MG Oral Tablet"), ("314076", "Lisinopril 10 MG Oral Tablet"),
    ("617310", "Atorvastatin 20 MG Oral Tablet"), ("197361", "Amlodipine 5 MG Oral Tablet"),
]
PLANTED_ALLERGIES = [("Penicillin", "Hives"), ("Sulfonamide antibiotics", "Rash"),
                     ("Codeine", "Nausea and vomiting"), ("Latex", "Contact dermatitis")]

TAG = re.compile(r"\s*\((?:disorder|finding|procedure|organism|substance|situation|morphologic abnormality)\)\s*$")
DOSE_RE = re.compile(r"\s(\d+(?:\.\d+)?)\s(MG|MCG)\b(?!\s*/)", re.I)


def clean(s):
    return TAG.sub("", s or "").strip()


def clean_person(s):
    return re.sub(r"\d+", "", s).strip()


def parse_date(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00")).date()


def fmt_dose(v):
    return f"{v:g}"


# ------------------------------------------------------------------ FHIR extraction
def extract(bundle, rng):
    res = [e["resource"] for e in bundle["entry"]]
    by_type = {}
    for r in res:
        by_type.setdefault(r["resourceType"], []).append(r)
    meds_by_id = {"urn:uuid:" + m["id"]: m for m in by_type.get("Medication", [])}

    p = by_type["Patient"][0]
    nm = p["name"][0]
    addr = p.get("address", [{}])[0]
    patient = {
        "name": clean_person(" ".join(nm.get("given", []) + [nm.get("family", "")])),
        "dob": p["birthDate"], "sex": p["gender"].capitalize(),
        "mrn": f"MRN-{rng.randint(100000, 999999)}",
        "city": addr.get("city"),
    }

    # encounter dates, chronological, distinct
    dates = sorted({parse_date(e["period"]["start"]) for e in by_type.get("Encounter", []) if "period" in e})
    while len(dates) < 3:  # tiny histories: pad backwards
        dates.insert(0, (dates[0] if dates else datetime(2020, 1, 1).date()) - timedelta(days=rng.randint(30, 200)))
    dates = dates[-3:]

    # conditions: recent distinct disorders
    conds, seen = [], set()
    for c in sorted(by_type.get("Condition", []), key=lambda c: c.get("onsetDateTime", ""), reverse=True):
        txt = c["code"]["text"]
        if "(disorder)" not in txt or txt in seen:
            continue
        seen.add(txt)
        conds.append({"name": clean(txt), "snomed": c["code"]["coding"][0]["code"],
                      "onset": c.get("onsetDateTime", "")[:10],
                      "status": c["clinicalStatus"]["coding"][0]["code"]})
        if len(conds) == 12:
            break

    # medications: active first, else most recent; max 4, de-duplicated by rxcui
    mreqs = sorted(by_type.get("MedicationRequest", []), key=lambda m: (m["status"] == "active", m["authoredOn"]), reverse=True)
    meds, seen = [], set()
    for m in mreqs:
        cc = m.get("medicationCodeableConcept") or meds_by_id[m["medicationReference"]["reference"]]["code"]
        code = cc["coding"][0]
        if code["code"] in seen:
            continue
        seen.add(code["code"])
        meds.append(make_med(code["code"], code["display"], rng))
        if len(meds) == 4:
            break

    # allergies (skip the generic "Allergic disposition")
    allergies = []
    for a in by_type.get("AllergyIntolerance", []):
        t = a["code"]["text"]
        if t.startswith("Allergic disposition"):
            continue
        reac = ""
        if a.get("reaction"):
            reac = clean(a["reaction"][0]["manifestation"][0]["text"])
        allergies.append({"substance": clean(t), "reaction": reac, "planted": False})

    # procedures (recent, skip screenings that read oddly)
    procs, seen = [], set()
    for pr in sorted(by_type.get("Procedure", []), key=lambda x: x.get("performedPeriod", {}).get("start", ""), reverse=True):
        t = clean(pr["code"]["text"])
        if t in seen or "screening" in t.lower() or "assessment" in t.lower():
            continue
        seen.add(t)
        procs.append({"name": t, "date": pr.get("performedPeriod", {}).get("start", "")[:10]})
        if len(procs) == 3:
            break

    # labs: numeric only
    labs = []
    for o in by_type.get("Observation", []):
        if o["category"][0]["coding"][0]["code"] != "laboratory" or "valueQuantity" not in o:
            continue
        loinc = next((c for c in o["code"]["coding"] if "loinc" in c["system"]), None)
        if not loinc:
            continue
        v = o["valueQuantity"]
        labs.append({"name": o["code"]["text"], "loinc": loinc["code"], "value": round(v["value"], 2),
                     "unit": v.get("unit", ""), "date": o["effectiveDateTime"][:10]})
    return patient, dates, conds, meds, allergies, procs, labs


def make_med(rxcui, display, rng):
    if display.startswith("{"):  # Synthea packs -> use brand name
        b = re.search(r"\[(.*?)\]", display)
        display = (b.group(1) if b else "Oral contraceptive pack")
    m = DOSE_RE.search(" " + display) if " / " not in display else None
    med = {"name": display, "rxcui": rxcui, "dose": None, "dose_value": None, "dose_unit": None,
           "frequency": rng.choice(FREQS)}
    if m and "MG/" not in display.upper():
        med["dose_value"], med["dose_unit"] = float(m.group(1)), m.group(2).lower()
        med["dose"] = f"{fmt_dose(med['dose_value'])} {med['dose_unit']}"
    if med["dose"] is None:
        med["frequency"] = "as directed"
    return med


def med_line(m):
    if m["dose"]:
        return f"{m['name']} - take {m['dose']} {m['frequency']}"
    return f"{m['name']} - {m['frequency']}"


# ------------------------------------------------------------------ rendering
def pick_labs(labs, doc_date):
    """Latest result per LOINC up to doc_date; fall back to earliest panel."""
    latest = OrderedDict()
    for l in sorted((l for l in labs if l["date"] <= doc_date.isoformat()), key=lambda l: l["date"]):
        latest[l["loinc"]] = l
    chosen = sorted(latest.values(), key=lambda l: l["date"], reverse=True)[:12]
    if len(chosen) < 3:
        chosen = sorted(labs, key=lambda l: l["date"])[:8]
    return chosen


def lab_line(l):
    return f"{l['name']}: {l['value']:g} {l['unit']} (collected {l['date']})"


def render_patient(idx, bundle_path, out_dir, env, rng, conflict, pdf=True):
    bundle = json.loads(Path(bundle_path).read_text())
    patient, dates, conds, meds, allergies, procs, labs = extract(bundle, rng)

    if conflict:  # guarantee a doseable med and a planted drug allergy
        if not any(m["dose"] for m in meds):
            code, disp = rng.choice(FALLBACK_MEDS)
            meds.append(make_med(code, disp, rng))
        sub, reac = rng.choice(PLANTED_ALLERGIES)
        allergies.append({"substance": sub, "reaction": reac, "planted": True})

    # doc order: conflict patients -> lab report is newest, oldest is DS or CL
    if conflict:
        order = rng.sample(["discharge_summary", "clinic_letter"], 2) + ["lab_report"]
    else:
        order = rng.sample(DOC_TYPES, 3)
    doc_dates = dict(zip(order, dates))  # ascending: order[0] is oldest

    facs = rng.sample(FACILITIES, 3)
    docs, truth = {}, {}
    oldest_clin, newer_clin = order[0], order[1]
    dose_target = next((m for m in meds if m["dose"]), None) if conflict else None

    for k, dtype in enumerate(order):
        fac = facs[k]
        facility = {"name": fac[0], "address": f"{fac[1]}, {patient['city'] or 'Springfield'}",
                    "phone": f"555-{rng.randint(100, 999)}-{rng.randint(1000, 9999)}"}
        style = {**rng.choice(STYLES), "accent": rng.choice(ACCENTS)}
        provider = rng.choice(DOCTORS)
        date = doc_dates[dtype]

        # per-document medications and allergies
        doc_meds = [dict(m) for m in meds] if dtype != "lab_report" else []
        doc_allergies = [a for a in allergies] if dtype != "lab_report" else []
        if conflict and dtype != "lab_report":
            if dtype == newer_clin:
                doc_allergies = [a for a in allergies if not a["planted"]]
                for m in doc_meds:
                    if dose_target and m["rxcui"] == dose_target["rxcui"]:
                        m["dose_value"] = m["dose_value"] * 2
                        m["dose"] = f"{fmt_dose(m['dose_value'])} {m['dose_unit']}"
        for m in doc_meds:
            m["line"] = med_line(m)
        no_allergy_text = "No known drug allergies" if conflict else "No known allergies"
        doc_labs = [dict(l, line=lab_line(l)) for l in pick_labs(labs, date)] if dtype == "lab_report" else []
        doc_procs = [x for x in procs if x["date"] and x["date"] <= date.isoformat()] if dtype == "discharge_summary" else []
        # only conditions that already existed on the document date (most recent 6)
        doc_conds = [c for c in conds if c["onset"] and c["onset"] <= date.isoformat()][:6] if dtype != "lab_report" else []
        if dtype == "lab_report" and doc_labs:  # report date = newest result in it
            date = max(date, parse_date(max(l["date"] for l in doc_labs)))

        ctx = dict(patient=patient, facility=facility, style=style, provider=provider, date=date.isoformat(),
                   conditions=doc_conds, medications=doc_meds, allergies=doc_allergies, procedures=doc_procs,
                   labs=doc_labs, no_allergy_text=no_allergy_text)
        html = env.get_template(f"{dtype}.html").render(**ctx)
        out_dir.mkdir(parents=True, exist_ok=True)
        if pdf:
            HTML(string=html, base_url=str(HERE)).write_pdf(out_dir / f"{dtype}.pdf")

        truth[dtype] = {
            "file": f"{dtype}.pdf", "date": date.isoformat(), "facility": facility["name"], "provider": provider,
            "medications": [{"name": m["name"], "rxcui": m["rxcui"], "dose": m["dose"], "frequency": m["frequency"]} for m in doc_meds],
            "allergies": [{"substance": a["substance"], "reaction": a["reaction"] or None} for a in doc_allergies],
            "conditions": [{"name": c["name"], "snomed": c["snomed"], "onset": c["onset"], "status": c["status"]} for c in doc_conds],
            "procedures": doc_procs,
            "labs": [{"name": l["name"], "loinc": l["loinc"], "value": l["value"], "unit": l["unit"], "date": l["date"]} for l in doc_labs],
        }
        docs[dtype] = truth[dtype]

    conflicts = []
    if conflict:
        old_d, new_d = truth[oldest_clin], truth[newer_clin]
        o = next(m for m in old_d["medications"] if m["rxcui"] == dose_target["rxcui"])
        n = next(m for m in new_d["medications"] if m["rxcui"] == dose_target["rxcui"])
        conflicts.append({"type": "dose_conflict", "medication": o["name"], "rxcui": o["rxcui"],
                          "values": [{"document": oldest_clin, "date": old_d["date"], "dose": o["dose"]},
                                     {"document": newer_clin, "date": new_d["date"], "dose": n["dose"]}]})
        pa = next(a for a in allergies if a["planted"])
        conflicts.append({"type": "allergy_only_in_oldest", "allergy": pa["substance"], "reaction": pa["reaction"],
                          "present_in": oldest_clin, "absent_from": newer_clin,
                          "dates": {"present": old_d["date"], "absent": new_d["date"]}})

    gt = {"patient_id": f"p{idx:02d}", "source_bundle": Path(bundle_path).name,
          "patient": {k: patient[k] for k in ("name", "dob", "sex", "mrn")},
          "documents": docs, "planted_conflicts": conflicts}
    (out_dir / "ground_truth.json").write_text(json.dumps(gt, indent=2, ensure_ascii=False))
    return gt


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fhir", default=str(HERE / "fhir"), help="folder of Synthea FHIR bundles (*.json)")
    ap.add_argument("--out", default=str(HERE / "out"))
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--conflicts", type=int, default=5, help="number of patients with planted conflicts")
    ap.add_argument("--no-pdf", action="store_true", help="skip PDF writing (debug)")
    a = ap.parse_args()

    files = sorted(p for p in Path(a.fhir).glob("*.json")
                   if not p.name.startswith(("hospitalInformation", "practitionerInformation")))
    rng = random.Random(a.seed)
    conflict_idx = set(rng.sample(range(len(files)), min(a.conflicts, len(files))))
    env = Environment(loader=FileSystemLoader(str(HERE / "templates")), autoescape=True)

    for i, f in enumerate(files, start=1):
        prng = random.Random(f"{a.seed}-{f.name}")  # stable per patient
        gt = render_patient(i, f, Path(a.out) / f"p{i:02d}", env, prng, (i - 1) in conflict_idx, pdf=not a.no_pdf)
        flag = " [CONFLICTS]" if gt["planted_conflicts"] else ""
        print(f"p{i:02d} {gt['patient']['name']}: 3 docs{flag}")
    print(f"done: {len(files)} patients, {len(conflict_idx)} with planted conflicts -> {a.out}")


if __name__ == "__main__":
    main()

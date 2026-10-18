#!/usr/bin/env python3
"""Render the hand-written demo patient: 5 documents for the demo account, 2 for live upload.

    python data/demo.py            # -> data/demo/account, data/demo/live, data/demo/ground_truth.json

On macOS WeasyPrint needs Homebrew's pango: prefix with DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib.

Elena Duarte's records come from a city hospital, a family clinic, a cardiologist and a pharmacy.
Two problems are planted for the demo:
  - metformin is 500 mg twice daily in the 2025 discharge, 1000 mg twice daily everywhere after;
  - the penicillin allergy appears only in the 2025 discharge; both later letters say
    "No known drug allergies".
The live documents add a later lab panel (HbA1c trend) and an urgent care letter with
lisinopril 20 mg (a new dose conflict) that lists the penicillin allergy again.

Load the account with api/reset_demo.py.
"""

import json
import random
from pathlib import Path

import cv2
from jinja2 import Environment, FileSystemLoader
from weasyprint import HTML

from augment import build_pipeline, put_on_table, render_pages

HERE = Path(__file__).parent
OUT = HERE / "demo"
SEED = 2026

PATIENT = {"name": "Elena Duarte", "dob": "1958-06-02", "sex": "Female"}
CITY = "Springfield"

HOSPITAL = {"name": "Springfield City Hospital", "address": f"400 Main Street, {CITY}", "phone": "555-210-4000"}
HOSPITAL_LAB = {**HOSPITAL, "name": "Springfield City Hospital Laboratory"}
FAMILY = {"name": "Maple Grove Family Clinic", "address": f"48 Maple Avenue, {CITY}", "phone": "555-318-2290"}
CARDIO = {"name": "Heartwell Cardiology Associates", "address": f"9 Northgate Plaza, {CITY}", "phone": "555-447-1800"}
PHARMACY = {"name": "Elm Street Pharmacy", "address": f"122 Elm Street, {CITY}", "phone": "555-602-7731"}
URGENT = {"name": "Riverside Urgent Care", "address": f"12 Harbor Road, {CITY}", "phone": "555-725-0119"}

FAMILY_DOCTOR = "Dr. R. Fernandez"
CARDIOLOGIST = "Dr. S. Johansson"

T2DM = {"name": "Type 2 diabetes mellitus", "onset": "2016-05-01", "status": "active"}
HTN = {"name": "Essential hypertension", "onset": "2012-09-01", "status": "active"}
HLD = {"name": "Hyperlipidemia", "onset": "2014-02-01", "status": "active"}
AFIB = {"name": "Paroxysmal atrial fibrillation", "onset": "2026-04-01", "status": "active"}

PENICILLIN = {"substance": "Penicillin", "reaction": "Hives and throat swelling"}


def med(name, dose, frequency, line=None):
    return {"name": name, "dose": dose, "frequency": frequency,
            "line": line or f"{name} {dose} tablet - take 1 tablet {frequency}"}


METFORMIN_500 = med("Metformin", "500 mg", "twice daily")
METFORMIN_1000 = med("Metformin", "1000 mg", "twice daily")
LISINOPRIL_10 = med("Lisinopril", "10 mg", "once daily")
LISINOPRIL_20 = med("Lisinopril", "20 mg", "once daily")
ATORVASTATIN = med("Atorvastatin", "20 mg", "once daily")
APIXABAN = med("Apixaban", "5 mg", "twice daily")
METOPROLOL = med("Metoprolol succinate ER", "25 mg", "once daily")
DOXYCYCLINE = med("Doxycycline", "100 mg", "twice daily",
                  "Doxycycline 100 mg capsule - take 1 capsule twice daily for 5 days, until 2025-03-19")


def lab(name, value, unit, ref, flag, date):
    flag_text = f" [{flag}]" if flag else ""
    return {"name": name, "value": value, "unit": unit, "date": date,
            "line": f"{name}: {value:g} {unit}{flag_text} (reference {ref}, collected {date})"}


def labs(date, a1c, glucose, creatinine, egfr, potassium, ldl=None):
    rows = [
        lab("Hemoglobin A1c", a1c, "%", "4.0-5.6", "H", date),
        lab("Glucose, fasting", glucose, "mg/dL", "70-99", "H", date),
        lab("Creatinine", creatinine, "mg/dL", "0.50-1.10", None, date),
        lab("eGFR", egfr, "mL/min/1.73m2", ">60", None, date),
        lab("Potassium", potassium, "mmol/L", "3.5-5.1", None, date),
    ]
    if ldl:
        rows.append(lab("LDL cholesterol", ldl, "mg/dL", "<100", None, date))
    return rows


def pharmacy_med(m, prescriber, filled):
    directions = {"once daily": "Take 1 tablet by mouth once daily",
                  "twice daily": "Take 1 tablet by mouth twice daily"}[m["frequency"]]
    return {**m, "name": f"{m['name']} {m['dose']} tablet", "directions": directions,
            "prescriber": prescriber, "filled": filled}


# file stem -> (template, rendered as photo, context). Stems sort in upload order.
ACCOUNT = {
    "01_city_hospital_discharge_2025-03": ("discharge_summary", False, dict(
        facility=HOSPITAL, provider="Dr. M. Okafor", date="2025-03-14", mrn="SCH-448213",
        conditions=[{"name": "Community-acquired pneumonia", "onset": "2025-03-10", "status": "resolved"},
                    T2DM, HTN, HLD],
        allergies=[PENICILLIN],
        medications=[METFORMIN_500, LISINOPRIL_10, ATORVASTATIN, DOXYCYCLINE],
        procedures=[{"name": "Chest X-ray", "date": "2025-03-10"}],
    )),
    "02_family_clinic_letter_2026-01": ("clinic_letter", True, dict(
        facility=FAMILY, provider=FAMILY_DOCTOR, date="2026-01-20", mrn="MGF-20931",
        recipient="Patient file", greeting="Diabetes and blood pressure review",
        intro="Elena Duarte was seen today for her routine diabetes and blood pressure review.",
        conditions=[T2DM, HTN, HLD], allergies=[],
        medications=[METFORMIN_1000, LISINOPRIL_10, ATORVASTATIN],
        plan="Continue the current treatment. Repeat HbA1c and kidney function in four weeks.",
    )),
    "03_lab_report_2026-02": ("lab_report", False, dict(
        facility=HOSPITAL_LAB, provider=FAMILY_DOCTOR, date="2026-02-09", mrn="SCH-448213",
        labs=labs("2026-02-09", a1c=7.6, glucose=148, creatinine=0.92, egfr=71, potassium=4.6, ldl=94),
    )),
    "04_cardiology_letter_2026-05": ("clinic_letter", False, dict(
        facility=CARDIO, provider=CARDIOLOGIST, date="2026-05-12", mrn="HCA-77120",
        recipient=f"{FAMILY_DOCTOR}, {FAMILY['name']}",
        conditions=[AFIB, T2DM, HTN, HLD], allergies=[],
        medications=[APIXABAN, METOPROLOL, METFORMIN_1000, LISINOPRIL_10, ATORVASTATIN],
        plan="Apixaban started for stroke prevention and metoprolol for rate control. "
             "Echocardiogram booked. Review in cardiology clinic in six months.",
    )),
    "05_pharmacy_medication_list_2026-08": ("pharmacy_list", True, dict(
        facility=PHARMACY, provider="M. Chen, PharmD", date="2026-08-21", mrn="",
        medications=[pharmacy_med(METFORMIN_1000, FAMILY_DOCTOR, "2026-08-02"),
                     pharmacy_med(LISINOPRIL_10, FAMILY_DOCTOR, "2026-08-02"),
                     pharmacy_med(ATORVASTATIN, FAMILY_DOCTOR, "2026-08-02"),
                     pharmacy_med(APIXABAN, CARDIOLOGIST, "2026-08-14"),
                     pharmacy_med(METOPROLOL, CARDIOLOGIST, "2026-08-14")],
    )),
}

LIVE = {
    "06_lab_report_2026-09": ("lab_report", False, dict(
        facility=HOSPITAL_LAB, provider=FAMILY_DOCTOR, date="2026-09-15", mrn="SCH-448213",
        labs=labs("2026-09-15", a1c=6.9, glucose=126, creatinine=0.95, egfr=69, potassium=4.4),
    )),
    "07_urgent_care_letter_2026-10": ("clinic_letter", True, dict(
        facility=URGENT, provider="Dr. K. Tanaka", date="2026-10-03", mrn="RUC-5512",
        recipient=f"{FAMILY_DOCTOR}, {FAMILY['name']}", greeting="Dear Dr. Fernandez,",
        intro="Your patient Elena Duarte attended urgent care today with a cough and fever.",
        conditions=[{"name": "Acute upper respiratory infection", "onset": "2026-10-01", "status": "active"},
                    AFIB, T2DM, HTN],
        allergies=[PENICILLIN],
        medications=[METFORMIN_1000, LISINOPRIL_20, ATORVASTATIN, APIXABAN, METOPROLOL],
        plan="Viral infection, supportive care only. No antibiotics given; note penicillin allergy. "
             "Return if fever persists beyond five days.",
    )),
}

STYLES = {
    "discharge_summary": {"font": "'DejaVu Serif', serif", "size": 10.5, "accent": "#0b5394"},
    "clinic_letter": {"font": "'Inter', 'DejaVu Sans', sans-serif", "size": 10.5, "accent": "#1b6b4a"},
    "lab_report": {"font": "'DejaVu Sans Mono', monospace", "size": 9.5, "accent": "#1f4f5f"},
    "pharmacy_list": {"font": "'DejaVu Sans', sans-serif", "size": 11, "accent": "#7a1f3d"},
}
CARDIO_STYLE = {"font": "'Bitstream Charter', serif", "size": 10.5, "accent": "#7a1f3d"}


def to_photo(pdf: Path, out: Path, key: str) -> None:
    """Phone-photo version of the first page, through the same pipeline as augment.py."""
    _, page = next(render_pages(pdf))
    rng = random.Random(key)
    image = build_pipeline(rng.randint(0, 2**31 - 1))(image=put_on_table(page, rng))["image"]
    cv2.imwrite(str(out), cv2.cvtColor(image, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 75])


def render(stem: str, template: str, photo: bool, ctx: dict, out_dir: Path, env: Environment) -> dict:
    style = CARDIO_STYLE if ctx["facility"] is CARDIO else STYLES[template]
    patient = {**PATIENT, "mrn": ctx["mrn"]}
    html = env.get_template(f"{template}.html").render(
        **{"conditions": [], "medications": [], "allergies": [], "procedures": [], "labs": [], **ctx},
        patient=patient, style=style, no_allergy_text="No known drug allergies",
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    pdf = out_dir / f"{stem}.pdf"
    HTML(string=html, base_url=str(HERE)).write_pdf(pdf)
    if photo:
        to_photo(pdf, out_dir / f"{stem}.jpg", f"{SEED}:{stem}")
        pdf.unlink()
    return {
        "file": f"{out_dir.name}/{stem}.{'jpg' if photo else 'pdf'}",
        "date": ctx["date"], "facility": ctx["facility"]["name"], "provider": ctx["provider"],
        "medications": [{k: m[k] for k in ("name", "dose", "frequency")} for m in ctx.get("medications", [])],
        "allergies": ctx.get("allergies", []),
        "labs": [{k: l[k] for k in ("name", "value", "unit", "date")} for l in ctx.get("labs", [])],
    }


def main():
    env = Environment(loader=FileSystemLoader(str(HERE / "templates")), autoescape=True)
    documents = {}
    for folder, docs in (("account", ACCOUNT), ("live", LIVE)):
        for stem, (template, photo, ctx) in docs.items():
            documents[stem] = render(stem, template, photo, ctx, OUT / folder, env)
            print(documents[stem]["file"])
    truth = {
        "patient": PATIENT,
        "documents": documents,
        "expected_conflicts": [
            {"kind": "dose", "name": "Metformin", "values": ["500 mg", "1000 mg"]},
            {"kind": "allergy_missing", "name": "Penicillin",
             "listed_in": ["01_city_hospital_discharge_2025-03"],
             "not_listed_in": ["02_family_clinic_letter_2026-01", "04_cardiology_letter_2026-05"]},
        ],
        "expected_after_live_upload": [
            {"kind": "dose", "name": "Lisinopril", "values": ["10 mg", "20 mg"]},
        ],
    }
    (OUT / "ground_truth.json").write_text(json.dumps(truth, indent=2) + "\n")
    print(f"done -> {OUT}")


if __name__ == "__main__":
    main()

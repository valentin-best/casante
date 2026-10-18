"""Normalize extracted items so the same medication, lab or allergy matches across documents.

Every item gets a `normalized` object with a `key`: two items with the same key in the
same section are the same thing, whatever the documents called them. Medications also get
a parsed dose and times per day, labs a LOINC code and a value in one canonical unit.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
from collections.abc import Callable, Iterable, Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
from rapidfuzz import fuzz, process

log = logging.getLogger(__name__)

RXNAV_URL = "https://rxnav.nlm.nih.gov/REST"
RXNAV_TIMEOUT = 5.0
# RxNav allows 20 requests/second per IP; calls take ~1 s, so 8 workers stays under it
RXNAV_WORKERS = 8
# After a failure, skip RxNav for a while instead of waiting on every name
RXNAV_COOLDOWN = 60.0
DEFAULT_CACHE_DIR = ".cache/rxnav"
NOT_INGREDIENTS = {"inert ingredients"}

Item = dict[str, Any]


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower()).strip()


# ------------------------------------------------------------------ medications


class RxNavUnavailable(RuntimeError):
    """RxNav could not be reached or returned something unreadable."""


def _rxnav(path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    try:
        response = httpx.get(f"{RXNAV_URL}{path}", params=params, timeout=RXNAV_TIMEOUT)
        response.raise_for_status()
        return response.json()
    except (httpx.HTTPError, ValueError) as error:
        raise RxNavUnavailable(str(error)) from error


def fetch_drug(name: str) -> dict[str, Any] | None:
    """Best RxNav match for a free-text drug name, with its ingredients. None if no match."""
    try:
        found = _rxnav("/approximateTerm.json", {"term": name, "maxEntries": 1})
        candidates = (found.get("approximateGroup") or {}).get("candidate") or []
        if not candidates:
            return None
        rxcui = candidates[0]["rxcui"]

        related = _rxnav(f"/rxcui/{rxcui}/related.json", {"tty": "IN"})
        groups = (related.get("relatedGroup") or {}).get("conceptGroup") or []
        names = {
            concept["name"].lower()
            for group in groups
            for concept in group.get("conceptProperties") or []
        }
    except (AttributeError, KeyError, TypeError) as error:
        raise RxNavUnavailable(f"Unexpected RxNav response: {error!r}") from error
    return {"rxcui": rxcui, "ingredients": sorted(names - NOT_INGREDIENTS)}


# Successful lookups only: a failure is retried once the cooldown is over.
_memory: dict[str, dict[str, Any] | None] = {}
_down_until = 0.0


def _cache_file(name: str) -> Path:
    directory = Path(os.getenv("RXNAV_CACHE_DIR", DEFAULT_CACHE_DIR))
    return directory / f"{hashlib.sha256(name.encode()).hexdigest()[:32]}.json"


def lookup_drug(name: str) -> dict[str, Any] | None:
    """fetch_drug, cached in memory and on disk. Raises RxNavUnavailable."""
    global _down_until
    name = _clean(name)
    if name in _memory:
        return _memory[name]

    path = _cache_file(name)
    try:
        match = json.loads(path.read_text())["match"]
    except (OSError, ValueError, KeyError):
        if time.monotonic() < _down_until:
            raise RxNavUnavailable("skipped: RxNav failed recently") from None
        try:
            match = fetch_drug(name)
        except RxNavUnavailable:
            _down_until = time.monotonic() + RXNAV_COOLDOWN
            raise
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"name": name, "match": match}))
        except OSError:
            log.warning("Could not write RxNav cache %s", path)

    _memory[name] = match
    return match


DOSE_FORM_WORDS = {
    "actuat", "auto-injector", "cap", "capsule", "capsules", "chewable", "coated",
    "cream", "day", "delayed", "disintegrating", "dr", "drug", "er", "extended", "film",
    "gel", "hr", "implant", "inhalant", "inhaler", "injectable", "injection",
    "intrauterine", "kit", "metered", "mucosal", "nasal", "ointment", "ophthalmic",
    "oral", "pack", "patch", "pen", "powder", "prefilled", "release", "solution",
    "spray", "sr", "suspension", "syringe", "system", "tab", "tablet", "tablets",
    "topical", "transdermal", "xr",
}  # fmt: skip
UNIT_WORDS = {
    "g", "iu", "mcg", "meq", "mg", "ml", "unit", "units", "unt", "ug", "µg", "%",
}  # fmt: skip
SALT_WORDS = {
    "acetate", "besylate", "bitartrate", "calcium", "chloride", "citrate", "fumarate",
    "hcl", "hydrobromide", "hydrochloride", "hyclate", "macrocrystals", "maleate",
    "mesylate", "monohydrate", "phosphate", "potassium", "sodium", "succinate",
    "sulfate", "tartrate",
}  # fmt: skip


def _is_noise(word: str) -> bool:
    """Strengths ("220", "0.3"), FDA application numbers ("nda020800"), units, forms."""
    return (
        word[0].isdigit()
        or re.fullmatch(r"(a?nda|bla)\d+", word) is not None
        or word in UNIT_WORDS
        or word.split("/")[0] in UNIT_WORDS
        or word in DOSE_FORM_WORDS
    )


def ingredient_from_name(name: str) -> str:
    """Fallback when RxNav is unavailable: drop strengths, units, dose forms and salts.

    "Acetaminophen 300 MG / Hydrocodone Bitartrate 5 MG Oral Tablet [Norco]"
    -> "acetaminophen / hydrocodone"
    """
    text = re.sub(r"\[[^\]]*\]", " ", _clean(name))  # brand tags like [Percocet]
    ingredients = set()
    for part in re.split(r"\s+/\s+", text):
        tokens = (word.strip(".,;:()") for word in part.split())
        words = [word for word in tokens if word and not _is_noise(word)]
        # Only drop salts when something else remains ("potassium chloride" stays)
        without_salts = [word for word in words if word not in SALT_WORDS]
        cleaned = " ".join(without_salts or words)
        if cleaned:
            ingredients.add(cleaned)
    return " / ".join(sorted(ingredients)) or _clean(name)


DOSE_RE = re.compile(
    r"(\d+(?:[.,]\d+)*)\s*"
    r"(mg|mcg|µg|μg|ug|g|ml|meq|iu|units?|tablets?|tabs?|capsules?|caps?|puffs?|drops?|%)"
    r"(?![a-z])",
    re.IGNORECASE,
)
DOSE_UNITS: dict[str, tuple[str, float]] = {
    "mg": ("mg", 1),
    "g": ("mg", 1000),
    "mcg": ("mg", 0.001),
    "µg": ("mg", 0.001),
    "μg": ("mg", 0.001),
    "ug": ("mg", 0.001),
    "ml": ("ml", 1),
    "meq": ("meq", 1),
    "iu": ("unit", 1),
    "unit": ("unit", 1),
    "units": ("unit", 1),
    "tablet": ("tablet", 1),
    "tablets": ("tablet", 1),
    "tab": ("tablet", 1),
    "tabs": ("tablet", 1),
    "capsule": ("capsule", 1),
    "capsules": ("capsule", 1),
    "cap": ("capsule", 1),
    "caps": ("capsule", 1),
    "puff": ("puff", 1),
    "puffs": ("puff", 1),
    "drop": ("drop", 1),
    "drops": ("drop", 1),
    "%": ("%", 1),
}


def _number(text: str) -> float:
    # "1,000" is a thousands separator; "0,5" is a decimal comma
    if re.fullmatch(r"\d{1,3}(,\d{3})+", text):
        return float(text.replace(",", ""))
    return float(text.replace(",", "."))


def parse_dose(dose: str | None) -> tuple[float, str] | None:
    """ "500 mg" -> (500, "mg"). Masses are converted to mg so doses compare directly."""
    if not dose:
        return None
    match = DOSE_RE.search(dose)
    if not match:
        return None
    unit, factor = DOSE_UNITS[match.group(2).lower()]
    value = float(round(_number(match.group(1)) * factor, 6))
    return (int(value) if value.is_integer() else value), unit


FREQUENCIES: list[tuple[str, float]] = [
    (r"\b(four times|4 times|qid|q\.i\.d)", 4),
    (r"\b(three times|3 times|tid|t\.i\.d)", 3),
    (r"\b(twice|two times|2 times|bid|b\.i\.d)", 2),
    (r"\b(weekly|once a week|every week)", 1 / 7),
    (
        (
            r"\b(once|daily|qd|q\.d|od|every day|nightly|at bedtime|qhs"
            r"|every morning|every evening|in the morning|in the evening)"
        ),
        1,
    ),
]


def times_per_day(frequency: str | None) -> float | None:
    """ "twice daily", "BID", "every 12 hours" -> 2. None when not a fixed schedule."""
    if not frequency:
        return None
    text = _clean(frequency)
    hours = re.search(r"every (\d+) hours?", text)
    if hours and int(hours.group(1)) > 0:
        return 24 / int(hours.group(1))
    for pattern, per_day in FREQUENCIES:
        if re.search(pattern + r"\b", text):
            return per_day
    return None


def _lookup_or_none(name: str) -> dict[str, Any] | None:
    try:
        return lookup_drug(name)
    except RxNavUnavailable as error:
        log.warning("RxNav unavailable for %r: %s", name, error)
        return None


def lookup_drugs(names: Iterable[str]) -> dict[str, dict[str, Any] | None]:
    """Parallel lookups, keyed by cleaned name. None when unmatched or RxNav is down."""
    unique = sorted({_clean(name) for name in names})
    if not unique:
        return {}
    with ThreadPoolExecutor(max_workers=min(RXNAV_WORKERS, len(unique))) as pool:
        return dict(zip(unique, pool.map(_lookup_or_none, unique)))


def normalize_medication(item: Item) -> dict[str, Any]:
    return _normalize_medication(item, _lookup_or_none(item["name"]))


def _normalize_medication(item: Item, match: dict[str, Any] | None) -> dict[str, Any]:
    name = item["name"]
    if match and match["ingredients"]:
        key = " / ".join(match["ingredients"])
    else:
        key = ingredient_from_name(name)
    dose = parse_dose(item.get("dose"))
    return {
        "key": key,
        "rxcui": match["rxcui"] if match else None,
        "dose_value": dose[0] if dose else None,
        "dose_unit": dose[1] if dose else None,
        "times_per_day": times_per_day(item.get("frequency")),
    }


# ------------------------------------------------------------------ labs


Convert = float | Callable[[float], float]


@dataclass(frozen=True)
class LabTest:
    loinc: str
    unit: str
    names: tuple[str, ...]
    convert: Mapping[str, Convert] = field(default_factory=dict)


COUNT_PER_UL = {
    "10*9/l": 1, "x10*9/l": 1, "k/ul": 1, "10*3/ul": 1, "x10*3/ul": 1,
    "thou/ul": 1, "/nl": 1, "g/l": 1,
}  # fmt: skip
CHOLESTEROL = {"mmol/l": 38.67}

# The LOINC codes Synthea uses, with common aliases. Blood and serum variants of the
# same analyte share an entry so they group together.
LAB_TESTS = [
    LabTest("6690-2", "10*3/uL", (
        "leukocytes [#/volume] in blood by automated count", "leukocytes",
        "white blood cells", "white blood cell count", "white cell count", "wbc",
    ), COUNT_PER_UL),
    LabTest("789-8", "10*6/uL", (
        "erythrocytes [#/volume] in blood by automated count", "erythrocytes",
        "red blood cells", "red blood cell count", "red cell count", "rbc",
    ), {"10*12/l": 1, "x10*12/l": 1, "m/ul": 1, "t/l": 1}),
    LabTest("718-7", "g/dL", (
        "hemoglobin [mass/volume] in blood", "hemoglobin", "haemoglobin", "hgb", "hb",
    ), {"g/l": 0.1, "mmol/l": 1.611}),
    LabTest("4544-3", "%", (
        "hematocrit [volume fraction] of blood by automated count", "hematocrit",
        "haematocrit", "hct",
    ), {"l/l": 100}),
    LabTest("787-2", "fL", (
        "mcv [entitic mean volume] in red blood cells by automated count",
        "mean corpuscular volume", "mcv",
    )),
    LabTest("785-6", "pg", (
        "mch [entitic mass] by automated count", "mean corpuscular hemoglobin", "mch",
    )),
    LabTest("786-4", "g/dL", (
        "mchc [entitic mass/volume] in red blood cells by automated count",
        "mean corpuscular hemoglobin concentration", "mchc",
    ), {"g/l": 0.1}),
    LabTest("788-0", "fL", (
        "erythrocyte [distwidth] in blood by automated count",
        "red cell distribution width", "rdw",
    )),
    LabTest("777-3", "10*3/uL", (
        "platelets [#/volume] in blood by automated count", "platelets",
        "platelet count", "plt",
    ), COUNT_PER_UL),
    LabTest("32207-3", "fL", (
        "platelet distribution width [entitic volume] in blood by automated count",
        "platelet distribution width", "pdw",
    )),
    LabTest("32623-1", "fL", (
        "platelet [entitic mean volume] in blood by automated count",
        "mean platelet volume", "mpv",
    )),
    LabTest("2345-7", "mg/dL", (
        "glucose [mass/volume] in serum or plasma", "glucose [mass/volume] in blood",
        "glucose", "blood glucose", "serum glucose", "plasma glucose",
    ), {"mmol/l": 18.016}),
    LabTest("2160-0", "mg/dL", (
        "creatinine [mass/volume] in serum or plasma",
        "creatinine [mass/volume] in blood", "creatinine", "serum creatinine",
    ), {"umol/l": 1 / 88.42}),
    LabTest("3094-0", "mg/dL", (
        "urea nitrogen [mass/volume] in serum or plasma",
        "urea nitrogen [mass/volume] in blood", "urea nitrogen",
        "blood urea nitrogen", "bun", "urea",
    ), {"mmol/l": 2.801}),
    LabTest("17861-6", "mg/dL", (
        "calcium [mass/volume] in serum or plasma", "calcium [mass/volume] in blood",
        "calcium", "serum calcium",
    ), {"mmol/l": 4.008}),
    LabTest("2951-2", "mmol/L", (
        "sodium [moles/volume] in serum or plasma", "sodium [moles/volume] in blood",
        "sodium", "na",
    ), {"meq/l": 1}),
    LabTest("2823-3", "mmol/L", (
        "potassium [moles/volume] in serum or plasma",
        "potassium [moles/volume] in blood", "potassium", "k",
    ), {"meq/l": 1}),
    LabTest("2075-0", "mmol/L", (
        "chloride [moles/volume] in serum or plasma",
        "chloride [moles/volume] in blood", "chloride", "cl",
    ), {"meq/l": 1}),
    LabTest("2028-9", "mmol/L", (
        "carbon dioxide total [moles/volume] in serum or plasma",
        "carbon dioxide total [moles/volume] in blood", "carbon dioxide",
        "total co2", "co2", "bicarbonate", "hco3",
    ), {"meq/l": 1}),
    LabTest("4548-4", "%", (
        "hemoglobin a1c/hemoglobin.total in blood", "hemoglobin a1c", "hba1c", "a1c",
        "glycated hemoglobin", "glycohemoglobin",
    ), {"mmol/mol": lambda v: v * 0.09148 + 2.152}),
    LabTest("33914-3", "mL/min", (
        ("glomerular filtration rate [volume rate/area] in serum or plasma "
         "by creatinine based formula (mdrd)/1.73 sq m"),
        "estimated glomerular filtration rate", "glomerular filtration rate",
        "egfr", "gfr",
    ), {"ml/min/1.73m2": 1, "ml/min/1.73": 1}),
    LabTest("2093-3", "mg/dL", (
        "cholesterol [mass/volume] in serum or plasma", "total cholesterol",
        "cholesterol",
    ), CHOLESTEROL),
    LabTest("2571-8", "mg/dL", (
        "triglyceride [mass/volume] in serum or plasma", "triglycerides",
        "triglyceride", "tg",
    ), {"mmol/l": 88.57}),
    LabTest("18262-6", "mg/dL", (
        "cholesterol in ldl [mass/volume] in serum or plasma by direct assay",
        "cholesterol in ldl [mass/volume] in serum or plasma by calculation",
        "ldl cholesterol", "ldl c", "ldl",
    ), CHOLESTEROL),
    LabTest("2085-9", "mg/dL", (
        "cholesterol in hdl [mass/volume] in serum or plasma", "hdl cholesterol",
        "hdl c", "hdl",
    ), CHOLESTEROL),
    LabTest("2885-2", "g/dL", (
        "protein [mass/volume] in serum or plasma", "total protein",
    ), {"g/l": 0.1}),
    LabTest("1751-7", "g/dL", (
        "albumin [mass/volume] in serum or plasma", "albumin", "serum albumin",
    ), {"g/l": 0.1}),
    LabTest("10834-0", "g/L", (
        "globulin [mass/volume] in serum by calculation", "globulin",
    ), {"g/dl": 10}),
    LabTest("1975-2", "mg/dL", (
        "bilirubin.total [mass/volume] in serum or plasma", "total bilirubin",
        "bilirubin",
    ), {"umol/l": 1 / 17.1}),
    LabTest("6768-6", "U/L", (
        "alkaline phosphatase [enzymatic activity/volume] in serum or plasma",
        "alkaline phosphatase", "alp",
    ), {"iu/l": 1}),
    LabTest("1742-6", "U/L", (
        "alanine aminotransferase [enzymatic activity/volume] in serum or plasma",
        "alanine aminotransferase", "alt", "sgpt",
    ), {"iu/l": 1}),
    LabTest("1920-8", "U/L", (
        "aspartate aminotransferase [enzymatic activity/volume] in serum or plasma",
        "aspartate aminotransferase", "ast", "sgot",
    ), {"iu/l": 1}),
]  # fmt: skip

FUZZY_CUTOFF = 92


def _lab_name(text: str) -> str:
    text = re.sub(r"[-_,:;]", " ", text.lower()).rstrip(". ")
    return re.sub(r"\s+", " ", text).strip()


_LAB_BY_NAME = {_lab_name(name): test for test in LAB_TESTS for name in test.names}


def match_lab(name: str) -> LabTest | None:
    """Exact name or alias first, then a close spelling (fuzzy ratio >= FUZZY_CUTOFF)."""
    cleaned = _lab_name(name)
    if cleaned in _LAB_BY_NAME:
        return _LAB_BY_NAME[cleaned]
    best = process.extractOne(
        cleaned, _LAB_BY_NAME.keys(), scorer=fuzz.ratio, score_cutoff=FUZZY_CUTOFF
    )
    return _LAB_BY_NAME[best[0]] if best else None


def _unit(unit: str) -> str:
    """ "x10^9/L" -> "x10*9/l", "µmol/L" -> "umol/l"."""
    unit = re.sub(r"\s+", "", unit.lower()).replace("µ", "u").replace("μ", "u")
    return re.sub(r"(?<=10)[\^e]", "*", unit)


def normalize_lab(item: Item) -> dict[str, Any]:
    value, unit = item.get("value"), item.get("unit")
    test = match_lab(item["test"])
    if test is None:
        return {
            "key": _clean(item["test"]),
            "loinc": None,
            "value": value,
            "unit": unit,
        }

    if unit and _unit(unit) == _unit(test.unit):
        unit = test.unit
    elif value is not None and unit and _unit(unit) in test.convert:
        convert = test.convert[_unit(unit)]
        if isinstance(convert, (int, float)):
            value = round(value * convert, 2)
        else:
            value = round(convert(value), 2)
        unit = test.unit
    return {"key": test.loinc, "loinc": test.loinc, "value": value, "unit": unit}


# ------------------------------------------------------------------ allergies, conditions


TERM_TAG = re.compile(
    r"\s*\((?:disorder|finding|procedure|organism|substance|situation"
    r"|morphologic abnormality)\)$"
)
SYNONYMS = {
    # allergies
    "pcn": "penicillin",
    "penicillins": "penicillin",
    "sulfa": "sulfonamide",
    "sulfa drugs": "sulfonamide",
    "sulfonamides": "sulfonamide",
    "sulfonamide antibiotics": "sulfonamide",
    "asa": "aspirin",
    "acetylsalicylic acid": "aspirin",
    "nsaids": "nsaid",
    "peanuts": "peanut",
    "tree nuts": "tree nut",
    # conditions
    "htn": "hypertension",
    "high blood pressure": "hypertension",
    "essential hypertension": "hypertension",
    "t2dm": "type 2 diabetes mellitus",
    "dm2": "type 2 diabetes mellitus",
    "type 2 diabetes": "type 2 diabetes mellitus",
    "diabetes mellitus type 2": "type 2 diabetes mellitus",
    "t1dm": "type 1 diabetes mellitus",
    "type 1 diabetes": "type 1 diabetes mellitus",
    "diabetes mellitus type 1": "type 1 diabetes mellitus",
    "high cholesterol": "hyperlipidemia",
    "copd": "chronic obstructive pulmonary disease",
    "afib": "atrial fibrillation",
    "a fib": "atrial fibrillation",
    "gerd": "gastroesophageal reflux disease",
    "ckd": "chronic kidney disease",
    "cad": "coronary artery disease",
    "heart attack": "myocardial infarction",
    "mi": "myocardial infarction",
    "uti": "urinary tract infection",
}


def term_key(text: str) -> str:
    """Lowercase, without SNOMED tags or "allergy to", then the synonym map."""
    term = TERM_TAG.sub("", _clean(text))
    term = re.sub(r"^allergy to ", "", term)
    term = re.sub(r" allergy$", "", term)
    return SYNONYMS.get(term, term)


# ------------------------------------------------------------------ whole record


def normalize_record(record: dict[str, list[Item]]) -> None:
    """Add `normalized` to every item in place. One parallel RxNav lookup per name."""
    medications = record.get("medications", [])
    matches = lookup_drugs(med["name"] for med in medications)
    for med in medications:
        med["normalized"] = _normalize_medication(med, matches[_clean(med["name"])])
    for lab in record.get("labs", []):
        lab["normalized"] = normalize_lab(lab)
    for allergy in record.get("allergies", []):
        allergy["normalized"] = {"key": term_key(allergy["substance"])}
    for section in ("conditions", "procedures"):
        for item in record.get(section, []):
            item["normalized"] = {"key": term_key(item["name"])}

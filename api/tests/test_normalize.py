from typing import Any

import pytest

from app.pipeline import normalize
from app.pipeline.normalize import (
    RxNavUnavailable,
    fetch_drug,
    ingredient_from_name,
    match_lab,
    normalize_lab,
    normalize_medication,
    normalize_record,
    parse_dose,
    term_key,
    times_per_day,
)


@pytest.fixture
def rxnav(monkeypatch):
    """A fake RxNav keyed by lowercase name; counts calls."""
    known: dict[str, dict | None] = {}
    calls: list[str] = []

    def fetch(name: str):
        calls.append(name)
        if name not in known:
            raise RxNavUnavailable("not in fake")
        return known[name]

    monkeypatch.setattr(normalize, "fetch_drug", fetch)
    return known, calls


# --- medications


def test_rxnav_ingredients_make_brand_and_product_names_match(rxnav):
    known, _ = rxnav
    known["metformin hydrochloride 500 mg oral tablet"] = {
        "rxcui": "861007",
        "ingredients": ["metformin"],
    }
    known["glucophage"] = {"rxcui": "151827", "ingredients": ["metformin"]}

    a = normalize_medication(
        {"name": "Metformin hydrochloride 500 MG Oral Tablet", "dose": "500 mg"}
    )
    b = normalize_medication({"name": "Glucophage", "dose": "1,000 mg"})

    assert a["key"] == b["key"] == "metformin"
    assert a["rxcui"] == "861007"
    assert (a["dose_value"], a["dose_unit"]) == (500, "mg")
    assert (b["dose_value"], b["dose_unit"]) == (1000, "mg")


def test_combination_products_list_every_ingredient(rxnav):
    known, _ = rxnav
    name = "acetaminophen 300 mg / hydrocodone bitartrate 5 mg oral tablet"
    known[name] = {"rxcui": "856987", "ingredients": ["acetaminophen", "hydrocodone"]}

    assert normalize_medication({"name": name})["key"] == "acetaminophen / hydrocodone"


def test_rxnav_down_falls_back_to_the_cleaned_name(rxnav):
    med = normalize_medication({"name": "Naproxen sodium 220 MG Oral Tablet"})

    assert med["key"] == "naproxen"
    assert med["rxcui"] is None


def test_rxnav_match_without_ingredients_falls_back_to_the_cleaned_name(rxnav):
    known, _ = rxnav
    known["jolivette 28 day"] = {"rxcui": "757594", "ingredients": []}

    med = normalize_medication({"name": "Jolivette 28 Day"})

    assert med["key"] == "jolivette"
    assert med["rxcui"] == "757594"


def test_lookups_are_cached_in_memory_and_on_disk(rxnav):
    known, calls = rxnav
    known["lisinopril"] = {"rxcui": "29046", "ingredients": ["lisinopril"]}

    normalize_medication({"name": "Lisinopril"})
    normalize_medication({"name": "lisinopril "})
    normalize._memory.clear()
    normalize_medication({"name": "LISINOPRIL"})

    assert calls == ["lisinopril"]


def test_failed_lookups_are_not_cached(rxnav):
    known, calls = rxnav
    normalize_medication({"name": "Lisinopril"})
    known["lisinopril"] = {"rxcui": "29046", "ingredients": ["lisinopril"]}
    normalize._down_until = 0.0  # cooldown over

    assert normalize_medication({"name": "Lisinopril"})["rxcui"] == "29046"
    assert calls == ["lisinopril", "lisinopril"]


def test_after_a_failure_rxnav_is_skipped_for_a_while(rxnav):
    known, calls = rxnav
    known["lisinopril"] = {"rxcui": "29046", "ingredients": ["lisinopril"]}

    normalize_medication({"name": "Metformin"})
    med = normalize_medication({"name": "Lisinopril"})

    assert calls == ["metformin"]
    assert med == normalize_medication({"name": "Lisinopril"})
    assert med["key"] == "lisinopril"
    assert med["rxcui"] is None


def test_fetch_drug_reads_ingredients_and_drops_placeholders(monkeypatch):
    responses = {
        "/approximateTerm.json": {
            "approximateGroup": {"candidate": [{"rxcui": "751905", "rank": "1"}]}
        },
        "/rxcui/751905/related.json": {
            "relatedGroup": {
                "conceptGroup": [
                    {
                        "tty": "IN",
                        "conceptProperties": [
                            {"rxcui": "4124", "name": "Ethinyl Estradiol"},
                            {"rxcui": "1", "name": "inert ingredients"},
                            {"rxcui": "31994", "name": "norgestimate"},
                        ],
                    }
                ]
            }
        },
    }
    monkeypatch.setattr(normalize, "_rxnav", lambda path, params=None: responses[path])

    assert fetch_drug("trinessa 28 day") == {
        "rxcui": "751905",
        "ingredients": ["ethinyl estradiol", "norgestimate"],
    }


def test_fetch_drug_without_candidates_is_no_match(monkeypatch):
    monkeypatch.setattr(
        normalize, "_rxnav", lambda path, params=None: {"approximateGroup": {}}
    )

    assert fetch_drug("asdfqwer") is None


def test_fetch_drug_treats_odd_responses_as_unavailable(monkeypatch):
    monkeypatch.setattr(
        normalize,
        "_rxnav",
        lambda path, params=None: {"approximateGroup": {"candidate": [{}]}},
    )

    with pytest.raises(RxNavUnavailable):
        fetch_drug("metformin")


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Naproxen sodium 220 MG Oral Tablet", "naproxen"),
        ("doxycycline hyclate 100 MG", "doxycycline"),
        ("Loratadine 5 MG Chewable Tablet", "loratadine"),
        (
            "Acetaminophen 300 MG / Hydrocodone Bitartrate 5 MG Oral Tablet",
            "acetaminophen / hydrocodone",
        ),
        ("NDA020800 0.3 ML Epinephrine 1 MG/ML Auto-Injector", "epinephrine"),
        ("Potassium chloride 20 MEQ Extended Release Tablet", "potassium chloride"),
        ("Atorvastatin calcium 20mg", "atorvastatin"),
        ("metformin", "metformin"),
        ("Vitamin B12 5 MG/ML Injectable Solution", "vitamin b12"),
        ("72 HR Fentanyl 0.025 MG/HR Transdermal System", "fentanyl"),
        (
            "levonorgestrel 0.000833 MG/HR Intrauterine System [Mirena]",
            "levonorgestrel",
        ),
        (
            (
                "Acetaminophen 325 MG / Oxycodone Hydrochloride 10 MG Oral Tablet "
                "[Percocet]"
            ),
            "acetaminophen / oxycodone",
        ),
        (
            (
                "nitrofurantoin, macrocrystals 25 MG / nitrofurantoin, monohydrate 75 MG "
                "Oral Capsule"
            ),
            "nitrofurantoin",
        ),
    ],
)
def test_ingredient_from_name(name, expected):
    assert ingredient_from_name(name) == expected


@pytest.mark.parametrize(
    ("dose", "expected"),
    [
        ("500 mg", (500, "mg")),
        ("500mg", (500, "mg")),
        ("1,000 mg", (1000, "mg")),
        ("0,5 mg", (0.5, "mg")),
        ("1 g", (1000, "mg")),
        ("100 mcg", (0.1, "mg")),
        ("100 µg", (0.1, "mg")),
        ("10 units", (10, "unit")),
        ("20 mEq", (20, "meq")),
        ("2 tablets", (2, "tablet")),
        ("5 mL", (5, "ml")),
        ("as directed", None),
        (None, None),
    ],
)
def test_parse_dose(dose, expected):
    assert parse_dose(dose) == expected


@pytest.mark.parametrize(
    ("frequency", "expected"),
    [
        ("once daily", 1),
        ("Daily", 1),
        ("at bedtime", 1),
        ("twice daily", 2),
        ("BID", 2),
        ("every 12 hours", 2),
        ("three times daily", 3),
        ("every 8 hours", 3),
        ("4 times a day", 4),
        ("once weekly", 1 / 7),
        ("as needed", None),
        ("as directed", None),
        (None, None),
    ],
)
def test_times_per_day(frequency, expected):
    assert times_per_day(frequency) == expected


# --- labs


@pytest.mark.parametrize(
    ("test", "loinc"),
    [
        ("Hemoglobin [Mass/volume] in Blood", "718-7"),
        ("Hemoglobin", "718-7"),
        ("Hgb", "718-7"),
        ("HbA1c", "4548-4"),
        ("Hemoglobin A1c/Hemoglobin.total in Blood", "4548-4"),
        ("LDL cholesterol", "18262-6"),
        ("HDL-Cholesterol", "2085-9"),
        ("WBC", "6690-2"),
        ("Leukocytes [#/volume] in Blood by Automated count", "6690-2"),
        # Blood and serum variants of the same analyte group together
        ("Glucose [Mass/volume] in Blood", "2345-7"),
        ("Glucose [Mass/volume] in Serum or Plasma", "2345-7"),
        ("Creatinine [Mass/volume] in Blood", "2160-0"),
        # Small wording differences
        ("Platelets [#/volume] in blood by automated count.", "777-3"),
        ("Haemoglobin", "718-7"),
    ],
)
def test_match_lab(test, loinc):
    entry = match_lab(test)
    assert entry is not None
    assert entry.loinc == loinc


@pytest.mark.parametrize(
    "test",
    [
        "Glucose [Mass/volume] in Urine by Test strip",
        "Protein [Mass/volume] in Urine by Test strip",
        "Vitamin D",
        "Body Height",
    ],
)
def test_match_lab_leaves_unknown_tests_alone(test):
    assert match_lab(test) is None


@pytest.mark.parametrize(
    ("test", "value", "unit", "expected"),
    [
        ("Glucose", 5.5, "mmol/L", (99.09, "mg/dL")),
        ("Glucose", 99, "mg/dL", (99, "mg/dL")),
        ("Creatinine", 88.4, "µmol/L", (1.0, "mg/dL")),
        ("Hemoglobin", 135, "g/L", (13.5, "g/dL")),
        ("Total cholesterol", 5.2, "mmol/l", (201.08, "mg/dL")),
        ("WBC", 6.1, "x10^9/L", (6.1, "10*3/uL")),
        ("Sodium", 140, "mEq/L", (140, "mmol/L")),
        ("HbA1c", 53, "mmol/mol", (7.0, "%")),
        # Unknown unit: keep what the document said
        ("Glucose", 99, "mg%", (99, "mg%")),
    ],
)
def test_normalize_lab_converts_units(test, value, unit, expected):
    lab = normalize_lab({"test": test, "value": value, "unit": unit})

    assert (lab["value"], lab["unit"]) == expected


def test_unmatched_lab_keys_on_its_cleaned_name():
    lab = normalize_lab({"test": "Vitamin D  ", "value": 30, "unit": "ng/mL"})

    assert lab == {"key": "vitamin d", "loinc": None, "value": 30, "unit": "ng/mL"}


# --- allergies and conditions


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("Penicillin", "penicillin "),
        ("PCN", "Penicillin"),
        ("Sulfa drugs", "Sulfonamide antibiotics"),
        ("Allergy to bee venom", "Bee venom"),
        ("Hypertension", "HTN"),
        ("Essential hypertension (disorder)", "High blood pressure"),
        ("Type 2 diabetes", "Diabetes mellitus type 2"),
    ],
)
def test_term_key_matches_synonyms(a, b):
    assert term_key(a) == term_key(b)


def test_term_key_keeps_distinct_terms_apart():
    assert term_key("Penicillin V") != term_key("Amoxicillin")


# --- whole record


def test_normalize_record_adds_normalized_to_every_item(rxnav):
    known, calls = rxnav
    known["metformin 500 mg"] = {"rxcui": "861007", "ingredients": ["metformin"]}
    record: dict[str, list[dict[str, Any]]] = {
        "medications": [
            {"name": "Metformin 500 mg", "dose": "500 mg", "frequency": "BID"},
            {"name": "Metformin 500 mg", "dose": "1000 mg", "frequency": "BID"},
        ],
        "allergies": [{"substance": "PCN"}],
        "conditions": [{"name": "HTN"}],
        "labs": [{"test": "Hgb", "value": 13.5, "unit": "g/dL"}],
        "procedures": [{"name": "Appendectomy"}],
    }

    normalize_record(record)

    assert [m["normalized"]["dose_value"] for m in record["medications"]] == [
        500,
        1000,
    ]
    assert record["medications"][0]["normalized"]["key"] == "metformin"
    assert record["medications"][0]["normalized"]["times_per_day"] == 2
    assert record["allergies"][0]["normalized"] == {"key": "penicillin"}
    assert record["conditions"][0]["normalized"] == {"key": "hypertension"}
    assert record["labs"][0]["normalized"]["loinc"] == "718-7"
    assert record["procedures"][0]["normalized"] == {"key": "appendectomy"}
    # One lookup per distinct name
    assert calls == ["metformin 500 mg"]

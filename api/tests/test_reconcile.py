from app.record import build_record


def doc(document_id: str, date: str | None, type: str = "clinic_letter", **sections):
    return {
        "id": document_id,
        "filename": f"{document_id}.pdf",
        "extraction": {
            "document": {"type": type, "provider": document_id, "date": date},
            **sections,
        },
    }


def med(name: str, evidence: str, **fields):
    return {"name": name, "evidence": [evidence], **fields}


def source(document_id: str, evidence: str):
    return {"document_id": document_id, "evidence": [evidence]}


# --- duplicates


def test_same_medication_in_two_documents_is_one_item_with_both_sources():
    record = build_record(
        [
            doc("a", "2026-01-10", medications=[med("Metformin", "a1", dose="500 mg")]),
            doc("b", "2026-03-02", medications=[med("metformin", "b1", dose="500mg")]),
        ]
    )

    [metformin] = record["medications"]
    assert metformin["sources"] == [source("a", "a1"), source("b", "b1")]
    assert record["conflicts"] == []


def test_merged_item_fills_missing_fields_from_other_documents():
    record = build_record(
        [
            doc(
                "a",
                "2026-01-10",
                medications=[med("Metformin", "a1", dose="500 mg", route="oral")],
            ),
            doc(
                "b",
                "2026-03-02",
                medications=[
                    med("Metformin", "b1", dose="500 mg", frequency="twice daily")
                ],
            ),
        ]
    )

    [metformin] = record["medications"]
    assert metformin["route"] == "oral"
    assert metformin["frequency"] == "twice daily"
    assert metformin["normalized"]["times_per_day"] == 2


def test_missing_frequency_in_one_document_is_not_a_conflict():
    record = build_record(
        [
            doc(
                "a",
                "2026-01-10",
                medications=[med("Metformin", "a1", dose="500 mg", frequency="BID")],
            ),
            doc("b", "2026-03-02", medications=[med("Metformin", "b1", dose="500 mg")]),
        ]
    )

    assert len(record["medications"]) == 1
    assert record["conflicts"] == []


# --- dose and frequency mismatches


def test_different_doses_stay_separate_and_are_flagged():
    record = build_record(
        [
            doc("a", "2026-01-10", medications=[med("Metformin", "a1", dose="500 mg")]),
            doc("b", "2026-03-02", medications=[med("Metformin", "b1", dose="1 g")]),
        ]
    )

    assert [m["dose"] for m in record["medications"]] == ["500 mg", "1 g"]
    assert record["conflicts"] == [
        {
            "kind": "dose",
            "section": "medications",
            "key": "metformin",
            "name": "Metformin",
            "variants": [
                {"value": "500 mg", "sources": [source("a", "a1")]},
                {"value": "1 g", "sources": [source("b", "b1")]},
            ],
        }
    ]


def test_different_frequencies_are_flagged():
    record = build_record(
        [
            doc(
                "a",
                "2026-01-10",
                medications=[
                    med("Metformin", "a1", dose="500 mg", frequency="once daily")
                ],
            ),
            doc(
                "b",
                "2026-03-02",
                medications=[med("Metformin", "b1", dose="500 mg", frequency="BID")],
            ),
        ]
    )

    [conflict] = record["conflicts"]
    assert conflict["kind"] == "frequency"
    assert [v["value"] for v in conflict["variants"]] == [
        "500 mg once daily",
        "500 mg BID",
    ]


def test_agreeing_documents_join_the_matching_side_of_a_conflict():
    record = build_record(
        [
            doc("a", "2026-01-10", medications=[med("Metformin", "a1", dose="500 mg")]),
            doc("b", "2026-02-10", medications=[med("Metformin", "b1", dose="1 g")]),
            doc("c", "2026-03-10", medications=[med("Metformin", "c1", dose="500 mg")]),
        ]
    )

    [conflict] = record["conflicts"]
    assert conflict["variants"] == [
        {"value": "500 mg", "sources": [source("a", "a1"), source("c", "c1")]},
        {"value": "1 g", "sources": [source("b", "b1")]},
    ]


# --- stopped medications


def test_medication_stopped_in_a_later_document_is_stopped_not_conflicting():
    record = build_record(
        [
            doc(
                "a",
                "2026-01-10",
                medications=[med("Metformin", "a1", dose="500 mg", status="active")],
            ),
            doc(
                "b",
                "2026-03-02",
                medications=[
                    med(
                        "Metformin",
                        "b1",
                        dose="1 g",
                        status="stopped",
                        stop_date="2026-03-01",
                    )
                ],
            ),
        ]
    )

    [metformin] = record["medications"]
    assert metformin["status"] == "stopped"
    assert metformin["stop_date"] == "2026-03-01"
    assert metformin["sources"] == [source("a", "a1"), source("b", "b1")]
    assert record["conflicts"] == []


def test_medication_restarted_after_being_stopped_is_active_with_stop_kept_as_history():
    record = build_record(
        [
            doc(
                "a",
                "2026-01-10",
                medications=[med("Metformin", "a1", dose="500 mg", status="stopped")],
            ),
            doc(
                "b",
                "2026-03-02",
                medications=[med("Metformin", "b1", dose="1 g", status="active")],
            ),
        ]
    )

    assert [(m["status"], m["sources"]) for m in record["medications"]] == [
        ("stopped", [source("a", "a1")]),
        ("active", [source("b", "b1")]),
    ]
    assert record["conflicts"] == []


def test_undated_document_cannot_stop_a_medication_listed_in_a_dated_one():
    record = build_record(
        [
            doc(
                "a",
                None,
                medications=[med("Metformin", "a1", dose="500 mg", status="stopped")],
            ),
            doc(
                "b",
                "2026-03-02",
                medications=[med("Metformin", "b1", dose="500 mg", status="active")],
            ),
        ]
    )

    assert [m["status"] for m in record["medications"]] == ["stopped", "active"]


# --- allergies


def test_allergy_missing_from_some_documents_is_flagged():
    record = build_record(
        [
            doc(
                "a", "2026-01-10", allergies=[{"substance": "PCN", "evidence": ["a1"]}]
            ),
            doc("b", "2026-03-02", allergies=[]),
            doc(
                "c",
                "2026-04-02",
                allergies=[{"substance": "Penicillin", "evidence": ["c1"]}],
            ),
        ]
    )

    [allergy] = record["allergies"]
    assert allergy["sources"] == [source("a", "a1"), source("c", "c1")]
    assert record["conflicts"] == [
        {
            "kind": "allergy_missing",
            "section": "allergies",
            "key": "penicillin",
            "name": "Penicillin",
            "variants": [
                {"value": "Listed", "sources": [source("a", "a1"), source("c", "c1")]},
                {
                    "value": "Not listed",
                    "sources": [{"document_id": "b", "evidence": []}],
                },
            ],
        }
    ]


def test_lab_reports_are_not_expected_to_list_allergies():
    record = build_record(
        [
            doc(
                "a", "2026-01-10", allergies=[{"substance": "PCN", "evidence": ["a1"]}]
            ),
            doc("b", "2026-03-02", type="lab_report"),
        ]
    )

    assert record["conflicts"] == []


def test_documents_without_extraction_are_not_expected_to_list_allergies():
    record = build_record(
        [
            doc(
                "a", "2026-01-10", allergies=[{"substance": "PCN", "evidence": ["a1"]}]
            ),
            {"id": "b", "filename": "b.pdf", "extraction": None},
        ]
    )

    assert record["conflicts"] == []


# --- labs


def lab(value: float, date: str, evidence: str, unit: str = "mg/dL"):
    return {
        "test": "Glucose",
        "value": value,
        "unit": unit,
        "date": date,
        "evidence": [evidence],
    }


def test_same_lab_result_in_two_documents_is_merged():
    record = build_record(
        [
            doc("a", "2026-01-10", labs=[lab(99, "2026-01-08", "a1")]),
            doc("b", "2026-03-02", labs=[lab(5.5, "2026-01-08", "b1", unit="mmol/L")]),
        ]
    )

    [glucose] = record["labs"]
    assert glucose["sources"] == [source("a", "a1"), source("b", "b1")]


def test_lab_results_on_different_dates_are_separate_and_not_conflicting():
    record = build_record(
        [
            doc("a", "2026-01-10", labs=[lab(99, "2026-01-08", "a1")]),
            doc("b", "2026-03-02", labs=[lab(130, "2026-03-01", "b1")]),
        ]
    )

    assert len(record["labs"]) == 2
    assert record["conflicts"] == []


def test_different_values_for_the_same_lab_on_the_same_date_are_flagged():
    record = build_record(
        [
            doc("a", "2026-01-10", labs=[lab(99, "2026-01-08", "a1")]),
            doc("b", "2026-03-02", labs=[lab(130, "2026-01-08", "b1")]),
        ]
    )

    assert len(record["labs"]) == 2
    [conflict] = record["conflicts"]
    assert conflict["kind"] == "lab_value"
    assert conflict["key"] == "2345-7"
    assert [v["value"] for v in conflict["variants"]] == ["99 mg/dL", "130 mg/dL"]


# --- conditions and procedures


def test_condition_status_comes_from_the_latest_document():
    record = build_record(
        [
            doc(
                "a",
                "2026-03-02",
                conditions=[{"name": "UTI", "status": "resolved", "evidence": ["a1"]}],
            ),
            doc(
                "b",
                "2026-01-10",
                conditions=[
                    {
                        "name": "Urinary tract infection",
                        "status": "active",
                        "evidence": ["b1"],
                    }
                ],
            ),
        ]
    )

    [uti] = record["conditions"]
    assert uti["status"] == "resolved"
    assert uti["sources"] == [source("b", "b1"), source("a", "a1")]


def test_same_procedure_on_different_dates_is_two_events():
    record = build_record(
        [
            doc(
                "a",
                "2026-01-10",
                procedures=[
                    {"name": "Colonoscopy", "date": "2025-01-01", "evidence": ["a1"]},
                    {"name": "Colonoscopy", "date": "2026-01-01", "evidence": ["a2"]},
                ],
            ),
            doc(
                "b",
                "2026-03-02",
                procedures=[
                    {"name": "colonoscopy", "date": "2026-01-01", "evidence": ["b1"]}
                ],
            ),
        ]
    )

    assert [len(p["sources"]) for p in record["procedures"]] == [1, 2]

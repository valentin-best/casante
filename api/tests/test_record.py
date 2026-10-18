from app.record import build_record


def row(document_id: str, **sections) -> dict:
    return {
        "id": document_id,
        "filename": f"{document_id}.pdf",
        "extraction": {
            "document": {
                "type": "clinic_letter",
                "provider": "Clinic A",
                "date": "2026-01-10",
            },
            **sections,
        },
    }


def test_items_cite_their_document_instead_of_bare_evidence():
    record = build_record(
        [
            row(
                "doc-a",
                medications=[
                    {"name": "Metformin", "dose": "500 mg", "evidence": ["p1-L3"]}
                ],
            )
        ]
    )

    assert record["medications"] == [
        {
            "name": "Metformin",
            "dose": "500 mg",
            "sources": [{"document_id": "doc-a", "evidence": ["p1-L3"]}],
            "normalized": {
                "key": "metformin",
                "rxcui": None,
                "dose_value": 500,
                "dose_unit": "mg",
                "times_per_day": None,
            },
        }
    ]


def test_items_with_a_matching_key_merge_across_documents():
    record = build_record(
        [
            row("doc-a", allergies=[{"substance": "PCN", "evidence": ["p1-L2"]}]),
            row(
                "doc-b", allergies=[{"substance": "Penicillin", "evidence": ["p2-L9"]}]
            ),
        ]
    )

    [allergy] = record["allergies"]
    assert allergy["normalized"]["key"] == "penicillin"
    assert [s["document_id"] for s in allergy["sources"]] == ["doc-a", "doc-b"]


def test_every_document_is_listed():
    record = build_record(
        [
            row(
                "doc-a", allergies=[{"substance": "Penicillin", "evidence": ["p1-L2"]}]
            ),
            row(
                "doc-b", allergies=[{"substance": "Penicillin", "evidence": ["p2-L9"]}]
            ),
        ]
    )

    assert [d["id"] for d in record["documents"]] == ["doc-a", "doc-b"]
    assert record["documents"][0]["provider"] == "Clinic A"
    assert record["conflicts"] == []


def test_document_without_extraction_still_listed():
    record = build_record([{"id": "doc-a", "filename": "a.pdf", "extraction": None}])

    assert record["documents"][0]["id"] == "doc-a"
    assert record["medications"] == []

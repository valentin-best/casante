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
        }
    ]


def test_items_from_every_document_are_listed():
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

    assert [a["sources"][0]["document_id"] for a in record["allergies"]] == [
        "doc-a",
        "doc-b",
    ]
    assert [d["id"] for d in record["documents"]] == ["doc-a", "doc-b"]
    assert record["documents"][0]["provider"] == "Clinic A"
    assert record["conflicts"] == []


def test_document_without_extraction_still_listed():
    record = build_record([{"id": "doc-a", "filename": "a.pdf", "extraction": None}])

    assert record["documents"][0]["id"] == "doc-a"
    assert record["medications"] == []

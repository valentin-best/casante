"""GET /record: everything extracted from the user's finished documents, with sources."""

from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.auth import CurrentUser
from app.db import Row, rows, supabase
from app.pipeline.fhir import record_to_fhir
from app.pipeline.normalize import normalize_record
from app.pipeline.reconcile import reconcile_record

router = APIRouter(tags=["record"])

SECTIONS = ("medications", "allergies", "conditions", "labs", "procedures")


def build_record(documents: list[Row]) -> dict[str, Any]:
    """Combine per-document extractions into one record: items normalized, merged
    across documents, and disagreements listed in `conflicts`."""
    record: dict[str, Any] = {
        "documents": [],
        **{section: [] for section in SECTIONS},
        "conflicts": [],
    }
    for row in documents:
        extraction = row["extraction"] or {}
        info = extraction.get("document") or {}
        record["documents"].append(
            {
                "id": row["id"],
                "filename": row["filename"],
                "type": info.get("type"),
                "provider": info.get("provider"),
                "date": info.get("date"),
            }
        )
        for section in SECTIONS:
            for item in extraction.get(section, []):
                fields = {
                    key: value for key, value in item.items() if key != "evidence"
                }
                source = {"document_id": row["id"], "evidence": item["evidence"]}
                record[section].append({**fields, "sources": [source]})
    normalize_record(record)
    reconcile_record(record)
    return record


@router.get("/record")
def get_record(user: CurrentUser) -> dict[str, Any]:
    found = rows(
        supabase()
        .table("documents")
        .select("id, filename, extraction")
        .eq("user_id", user.id)
        .eq("status", "done")
        .order("created_at")
        .execute()
    )
    return build_record(found)


@router.get("/record/fhir", response_class=JSONResponse)
def get_fhir_record(user: CurrentUser) -> JSONResponse:
    record = get_record(user)
    bundle = record_to_fhir(record, user.id)
    return JSONResponse(
        content=bundle,
        media_type="application/fhir+json",
        headers={
            "Content-Disposition": 'attachment; filename="unified-record.fhir.json"'
        },
    )

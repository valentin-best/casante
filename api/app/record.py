"""GET /record: everything extracted from the user's finished documents, with sources."""

from typing import Any

from fastapi import APIRouter

from app.auth import CurrentUser
from app.db import Row, rows, supabase
from app.pipeline.normalize import normalize_record

router = APIRouter(tags=["record"])

SECTIONS = ("medications", "allergies", "conditions", "labs", "procedures")


def build_record(documents: list[Row]) -> dict[str, Any]:
    """Flatten per-document extractions into one record, each item with its `normalized` key.

    TODO(#12): merge items with the same key and flag conflicts.
    """
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

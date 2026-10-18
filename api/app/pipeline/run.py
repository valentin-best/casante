"""Background job: run one uploaded document through the pipeline and save each step."""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from typing import Any

from app.db import BUCKET, rows, supabase
from app.pipeline.extract import extract_document
from app.pipeline.ingest import ingest_pdf

log = logging.getLogger(__name__)

NO_TEXT = (
    "We couldn't find any text in this document. Photos and scans aren't supported yet."
)
GENERIC_ERROR = "Something went wrong while processing this document."
INTERRUPTED = "Processing was interrupted. Please try again."


class ProcessingError(Exception):
    """A failure whose message is safe to show to the user."""


def _update(document_id: str, **fields: Any) -> None:
    supabase().table("documents").update(fields).eq("id", document_id).execute()


def page_image_path(user_id: str, document_id: str, page: int) -> str:
    return f"{user_id}/{document_id}/pages/{page}.png"


def fail_interrupted() -> None:
    """A restart kills running background tasks. Mark their documents failed so they can be retried."""
    supabase().table("documents").update(
        {
            "status": "failed",
            "error": INTERRUPTED,
        }
    ).in_("status", ["queued", "reading", "extracting"]).execute()


def process_document(document_id: str) -> None:
    """queued -> reading -> extracting -> done or failed with a readable error."""
    try:
        row = rows(
            supabase()
            .table("documents")
            .select("user_id, storage_path, content_type")
            .eq("id", document_id)
            .execute()
        )[0]
        _update(document_id, status="reading", error=None)

        # TODO(#10): photos and scanned pages go through OCR here.
        if row["content_type"] != "application/pdf":
            raise ProcessingError(NO_TEXT)

        storage = supabase().storage.from_(BUCKET)
        data = storage.download(row["storage_path"])

        with tempfile.TemporaryDirectory() as tmp:
            ingested = ingest_pdf(data, tmp)
            if not any(page.lines for page in ingested.pages):
                raise ProcessingError(NO_TEXT)
            for page in ingested.pages:
                storage.upload(
                    page_image_path(row["user_id"], document_id, page.number),
                    Path(page.image_path).read_bytes(),
                    {"content-type": "image/png", "upsert": "true"},
                )

        _update(
            document_id,
            status="extracting",
            file_hash=ingested.file_hash,
            pages=[page.model_dump(exclude={"image_path"}) for page in ingested.pages],
        )

        extraction = extract_document(ingested)
        _update(
            document_id, status="done", extraction=extraction.model_dump(mode="json")
        )

    except Exception as error:
        log.exception("Processing failed for document %s", document_id)
        message = str(error) if isinstance(error, ProcessingError) else GENERIC_ERROR
        _update(document_id, status="failed", error=message)

"""Upload, process and follow documents. Every query filters by the caller's user id."""

from datetime import datetime
from uuid import UUID, uuid4

from fastapi import APIRouter, BackgroundTasks, HTTPException, UploadFile, status
from pydantic import BaseModel

from app.auth import CurrentUser, User
from app.db import BUCKET, Row, rows, supabase
from app.pipeline.ingest import Line
from app.pipeline.run import page_image_path, process_document

router = APIRouter(prefix="/documents", tags=["documents"])

MAX_BYTES = 20 * 1024 * 1024  # 20 MB
EXTENSIONS = {
    "application/pdf": "pdf",
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
}
SIGNED_URL_SECONDS = 60 * 60
COLUMNS = "id, filename, content_type, status, error, created_at"


class DocumentOut(BaseModel):
    id: UUID
    filename: str
    content_type: str
    status: str
    error: str | None
    created_at: datetime


class PageOut(BaseModel):
    number: int
    width: int
    height: int
    image_url: str
    lines: list[Line]


def _owned(document_id: UUID, user: User, columns: str = COLUMNS) -> Row:
    found = rows(
        supabase()
        .table("documents")
        .select(columns)
        .eq("id", str(document_id))
        .eq("user_id", user.id)
        .limit(1)
        .execute()
    )
    if not found:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")
    return found[0]


@router.post("", status_code=status.HTTP_201_CREATED)
def upload_document(file: UploadFile, user: CurrentUser) -> DocumentOut:
    content_type = file.content_type or ""
    extension = EXTENSIONS.get(content_type)
    if extension is None:
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            "Upload a PDF or a JPEG, PNG or WebP image.",
        )
    data = file.file.read(MAX_BYTES + 1)
    if not data:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "The file is empty.")
    if len(data) > MAX_BYTES:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            "Files can be at most 20 MB.",
        )
    row = save_document(
        user.id, file.filename or f"document.{extension}", content_type, data
    )
    return DocumentOut(**row)


def save_document(user_id: str, filename: str, content_type: str, data: bytes) -> Row:
    """Store the original file and add its queued row. content_type must be in EXTENSIONS."""
    document_id = str(uuid4())
    storage_path = f"{user_id}/{document_id}/original.{EXTENSIONS[content_type]}"
    supabase().storage.from_(BUCKET).upload(
        storage_path, data, {"content-type": content_type}
    )
    return rows(
        supabase()
        .table("documents")
        .insert(
            {
                "id": document_id,
                "user_id": user_id,
                "filename": filename,
                "content_type": content_type,
                "storage_path": storage_path,
            }
        )
        .execute()
    )[0]


@router.post("/{document_id}/process", status_code=status.HTTP_202_ACCEPTED)
def start_processing(
    document_id: UUID, background: BackgroundTasks, user: CurrentUser
) -> DocumentOut:
    if _owned(document_id, user)["status"] in ("reading", "extracting"):
        raise HTTPException(
            status.HTTP_409_CONFLICT, "The document is already being processed."
        )
    row = rows(
        supabase()
        .table("documents")
        .update({"status": "queued", "error": None})
        .eq("id", str(document_id))
        .execute()
    )[0]
    background.add_task(process_document, str(document_id))
    return DocumentOut(**{key: row[key] for key in DocumentOut.model_fields})


@router.get("/{document_id}")
def get_document(document_id: UUID, user: CurrentUser) -> DocumentOut:
    return DocumentOut(**_owned(document_id, user))


@router.get("/{document_id}/pages/{page}")
def get_page(document_id: UUID, page: int, user: CurrentUser) -> PageOut:
    pages = _owned(document_id, user, "pages")["pages"] or []
    match = next((p for p in pages if p["number"] == page), None)
    if match is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Page not found")
    signed = (
        supabase()
        .storage.from_(BUCKET)
        .create_signed_url(
            page_image_path(user.id, str(document_id), page), SIGNED_URL_SECONDS
        )
    )
    image_url = signed["signedURL"]
    if image_url is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Page image not found")
    return PageOut(**match, image_url=image_url)

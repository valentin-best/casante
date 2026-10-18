"""Extract structured, line-cited facts from an ingested document with Gemini."""

from __future__ import annotations

import json
import os
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from google.genai.errors import APIError
from pydantic import ValidationError

from app.pipeline.ingest import IngestResult, Line
from app.pipeline.schemas import ExtractionResult

DEFAULT_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")
DEFAULT_CACHE_DIR = ".cache/gemini"
MAX_API_ATTEMPTS = 3
INVALID_JSON_ATTEMPTS = 2

SYSTEM_PROMPT = """You extract facts from medical documents.
Use only information explicitly written in the supplied numbered lines.
Never infer a diagnosis, treatment, date, or other fact. Use null when a scalar
field is not stated. Dates must be ISO YYYY-MM-DD when explicitly stated and
otherwise null. Every medication, allergy, condition, lab, and procedure must
include at least one exact line id in its evidence array. Do not cite a line
that does not support the item. Return only JSON matching the supplied schema."""


class ExtractionError(RuntimeError):
    """Raised when Gemini cannot return a valid extraction."""


def _lines(value: IngestResult | Sequence[Line]) -> tuple[list[Line], str | None]:
    if isinstance(value, IngestResult):
        return [line for page in value.pages for line in page.lines], value.file_hash
    return list(value), None


def _prompt(lines: Sequence[Line]) -> str:
    numbered = "\n".join(f"[{line.id}] {line.text}" for line in lines)
    return (
        "Extract the document represented by these numbered lines. "
        "The evidence values must be line ids exactly as written.\n\n"
        f"{numbered}"
    )


def _is_retryable(error: Exception) -> bool:
    status = getattr(error, "status_code", None) or getattr(error, "code", None)
    if status in {408, 429, 500, 502, 503, 504}:
        return True
    message = str(error).lower()
    return any(
        marker in message
        for marker in ("rate limit", "too many requests", "temporarily unavailable")
    )


def _response_text(response: Any) -> str:
    text = getattr(response, "text", None)
    if not isinstance(text, str) or not text.strip():
        raise ExtractionError("Gemini returned an empty response")
    return text


def _parse(response: Any, valid_ids: set[str]) -> ExtractionResult:
    try:
        payload = json.loads(_response_text(response))
        result = ExtractionResult.model_validate(payload)
    except (json.JSONDecodeError, ValidationError, ExtractionError) as error:
        raise ExtractionError("Gemini returned invalid extraction JSON") from error

    for field in ("medications", "allergies", "conditions", "labs", "procedures"):
        kept = []
        for item in getattr(result, field):
            evidence = [line_id for line_id in item.evidence if line_id in valid_ids]
            if evidence:
                kept.append(item.model_copy(update={"evidence": evidence}))
        setattr(result, field, kept)
    return result


def _client_generate(client: Any, prompt: str, model: str) -> Any:
    from google.genai import types

    return client.models.generate_content(
        model=model,
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            response_mime_type="application/json",
            response_schema=ExtractionResult.model_json_schema(),
        ),
    )


def extract_document(
    document: IngestResult | Sequence[Line],
    *,
    client: Any | None = None,
    model: str = DEFAULT_MODEL,
    cache_dir: str | Path | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> ExtractionResult:
    """Extract one document, using a JSON cache when its ingest hash is known."""
    lines, file_hash = _lines(document)
    cache_path = None
    if file_hash:
        cache_path = Path(cache_dir or os.getenv("GEMINI_CACHE_DIR", DEFAULT_CACHE_DIR))
        cache_path = cache_path / f"{file_hash}.json"
        if cache_path.exists():
            try:
                return ExtractionResult.model_validate_json(cache_path.read_text())
            except (OSError, ValidationError, json.JSONDecodeError) as error:
                raise ExtractionError(
                    f"Invalid extraction cache: {cache_path}"
                ) from error

    if client is None:
        from google import genai

        client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

    valid_ids = {line.id for line in lines}
    prompt = _prompt(lines)
    last_error: Exception | None = None
    invalid_json_attempts = 0
    for attempt in range(MAX_API_ATTEMPTS):
        try:
            result = _parse(_client_generate(client, prompt, model), valid_ids)
            if cache_path:
                cache_path.parent.mkdir(parents=True, exist_ok=True)
                cache_path.write_text(result.model_dump_json(indent=2))
            return result
        except ExtractionError as error:
            last_error = error
            invalid_json_attempts += 1
            if invalid_json_attempts >= INVALID_JSON_ATTEMPTS:
                break
        except (APIError, ConnectionError, OSError, TimeoutError) as error:
            last_error = error
            if not _is_retryable(error) or attempt == MAX_API_ATTEMPTS - 1:
                break
        if attempt < MAX_API_ATTEMPTS - 1:
            sleep(2**attempt)

    raise ExtractionError("Gemini extraction failed") from last_error


def extract_items(
    document: IngestResult | Sequence[Line],
    **kwargs: Any,
) -> dict[str, Any]:
    """Compatibility entry point returning the JSON-shaped extraction mapping."""
    return extract_document(document, **kwargs).model_dump(mode="json")

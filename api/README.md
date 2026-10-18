# CaSanté API

FastAPI service that runs the document pipeline. Every route except `/health` and `/share/{token}` needs a Supabase access token in `Authorization: Bearer <token>`.

## Run locally

```sh
cp .env.example .env   # fill in the values
uv sync
uv run uvicorn app.main:app --reload --env-file .env
```

- `GET /health`: liveness check, no auth
- `GET /me`: returns the signed-in user, handy to test the web login
- `GET /record`: returns the unified record as JSON
- `GET /record/fhir`: downloads the unified record as a FHIR R4 `Bundle`

## Gemini extraction

The extraction pipeline numbers text-layer lines during ingestion, then sends only
those numbered lines to Gemini Flash. Set `GEMINI_API_KEY` before calling
`app.pipeline.extract.extract_items`. Results are validated against the Pydantic
schema, facts citing unknown line ids are dropped, and successful extractions are
cached as `<file_sha256>.json` under `.cache/gemini` (override with
`GEMINI_CACHE_DIR`). Use `extract_document` when a typed `ExtractionResult` is
preferred.

```python
from app.pipeline.extract import extract_items
from app.pipeline.ingest import ingest_pdf

ingested = ingest_pdf(pdf_bytes, "ingest_out")
extraction = extract_items(ingested)
```

The first five sample PDFs can be exercised without changing the source files:

```sh
find ../data/pdfs -type f -name '*.pdf' | sort | head -5 | while read -r pdf; do
  uv run python -m app.pipeline.ingest "$pdf" /tmp/casante-ingest
done
```

## Test

```sh
uv run pytest
```

## Docker

```sh
docker build -t casante-api .
docker run --env-file .env -p 8000:8000 casante-api
```

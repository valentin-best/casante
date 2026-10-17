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

## Test

```sh
uv run pytest
```

## Docker

```sh
docker build -t casante-api .
docker run --env-file .env -p 8000:8000 casante-api
```

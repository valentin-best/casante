FROM python:3.11-slim

# The app runs from uv's venv; the system setuptools only adds vendored CVEs
RUN pip uninstall -y setuptools

COPY --from=ghcr.io/astral-sh/uv:0.13.0 /uv /uvx /bin/

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:$PATH"

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# RapidOCR downloads its models on first use; fetch them now, not at startup
RUN python -c "from rapidocr import RapidOCR; RapidOCR()"

COPY app ./app

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]

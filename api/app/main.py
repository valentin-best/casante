import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import documents, record
from app.auth import CurrentUser, User
from app.pipeline.ocr import load_engine
from app.pipeline.run import fail_interrupted


@asynccontextmanager
async def lifespan(_app: FastAPI):
    fail_interrupted()
    load_engine()
    yield


app = FastAPI(title="CaSanté API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[os.environ["ALLOWED_ORIGIN"]],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(documents.router)
app.include_router(record.router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/me")
def me(user: CurrentUser) -> User:
    return user

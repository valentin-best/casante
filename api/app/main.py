import os
from typing import Annotated

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.auth import User, current_user

app = FastAPI(title="CaSanté API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[os.environ["ALLOWED_ORIGIN"]],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/me")
def me(user: Annotated[User, Depends(current_user)]) -> User:
    return user

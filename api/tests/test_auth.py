import time
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient

from app import auth
from app.main import app

ISSUER = "https://test.supabase.co/auth/v1"
SIGNING_KEY = ec.generate_private_key(ec.SECP256R1())
OTHER_KEY = ec.generate_private_key(ec.SECP256R1())


class FakeJWKSClient:
    def get_signing_key_from_jwt(self, token: str) -> SimpleNamespace:
        return SimpleNamespace(key=SIGNING_KEY.public_key())


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(auth, "_jwks_client", lambda: FakeJWKSClient())
    return TestClient(app)


def make_token(key=SIGNING_KEY, algorithm: str = "ES256", **overrides) -> str:
    claims = {
        "sub": "user-123",
        "email": "patient@example.com",
        "aud": "authenticated",
        "iss": ISSUER,
        "exp": int(time.time()) + 3600,
    } | overrides
    return jwt.encode(claims, key, algorithm=algorithm)


def get_me(client: TestClient, token: str):
    return client.get("/me", headers={"Authorization": f"Bearer {token}"})


def test_health_needs_no_auth(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_valid_token_returns_user(client: TestClient) -> None:
    response = get_me(client, make_token())
    assert response.status_code == 200
    assert response.json() == {"id": "user-123", "email": "patient@example.com"}


def test_missing_token_is_rejected(client: TestClient) -> None:
    assert client.get("/me").status_code == 401


@pytest.mark.parametrize(
    "token",
    [
        make_token(exp=int(time.time()) - 10),
        make_token(aud="anon"),
        make_token(iss="https://other.supabase.co/auth/v1"),
        make_token(key=OTHER_KEY),
        make_token(key="a-shared-secret-that-is-32-bytes!", algorithm="HS256"),
        "not-a-jwt",
    ],
    ids=["expired", "wrong-audience", "wrong-issuer", "wrong-key", "hs256", "garbage"],
)
def test_bad_tokens_are_rejected(client: TestClient, token: str) -> None:
    assert get_me(client, token).status_code == 401

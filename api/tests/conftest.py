import os

import pytest

os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("ALLOWED_ORIGIN", "http://localhost:3000")


@pytest.fixture(autouse=True)
def offline_rxnav(monkeypatch, tmp_path):
    """Tests never call RxNav: lookups fail (name fallback) unless a test fakes them."""
    from app.pipeline import normalize

    def unavailable(name: str):
        raise normalize.RxNavUnavailable("offline in tests")

    monkeypatch.setenv("RXNAV_CACHE_DIR", str(tmp_path / "rxnav"))
    monkeypatch.setattr(normalize, "fetch_drug", unavailable)
    monkeypatch.setattr(normalize, "_down_until", 0.0)
    normalize._memory.clear()

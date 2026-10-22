from pathlib import Path

import pytest

FIX = Path(__file__).parent / "fixtures"


def fixture_text(name: str) -> str:
    return (FIX / name).read_text(encoding="utf-8")


@pytest.fixture(autouse=True)
def no_real_keyring(monkeypatch, tmp_path):
    """Tests never touch the developer's real keyring or state."""
    from screener_india_mcp import credentials

    store: dict = {}
    monkeypatch.setattr(credentials, "keyring_available", lambda: True)

    class FakeKR:
        def get_password(self, svc, key):
            return store.get(key)

        def set_password(self, svc, key, val):
            store[key] = val

        def delete_password(self, svc, key):
            store.pop(key, None)

    monkeypatch.setattr(credentials, "_keyring", lambda: FakeKR())
    monkeypatch.delenv("SCREENER_EMAIL", raising=False)
    monkeypatch.delenv("SCREENER_PASSWORD", raising=False)
    monkeypatch.setenv("SCREENER_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("SCREENER_CACHE_DIR", str(tmp_path / "cache"))
    yield store

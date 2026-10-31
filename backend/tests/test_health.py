from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app


def test_health():
    r = TestClient(app).get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_settings_defaults():
    s = get_settings()
    assert s.OPENAI_EMBED_MODEL == "text-embedding-3-small"
    assert s.RECALL_BASE_URL.startswith("https://")

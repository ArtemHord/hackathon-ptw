import json
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from app import db
from app.config import get_settings
from app.main import app

RECALL = "https://eu-central-1.recall.ai"
MOCKS = Path(__file__).resolve().parents[2] / "mocks"
AUTH = {"Authorization": "Bearer demo-t"}


@pytest.fixture(autouse=True)
def env(monkeypatch):
    for k, v in {
        "RECALL_API_KEY": "rk_test",
        "RECALL_BASE_URL": RECALL,
        "PUBLIC_BASE_URL": "https://crew.example.com",
        "WEBHOOK_TOKEN": "wh-t",
        "DEMO_TOKEN": "demo-t",
        "DATABASE_URL": "",
    }.items():
        monkeypatch.setenv(k, v)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def store(monkeypatch):
    """In-memory replacement for the db helpers."""
    meetings: dict[str, dict] = {}
    briefs: list[tuple[str, str]] = []

    async def insert_meeting(**kw):
        m = {"id": f"m_{len(meetings) + 1:02d}", "recall_bot_id": None, **kw}
        meetings[m["id"]] = m
        return dict(m)

    async def get_meeting(mid):
        return dict(meetings[mid]) if mid in meetings else None

    async def update_meeting(mid, **kw):
        meetings[mid].update(kw)
        return dict(meetings[mid])

    async def insert_brief(mid, text):
        briefs.append((mid, text))

    for name, fn in {
        "insert_meeting": insert_meeting,
        "get_meeting": get_meeting,
        "update_meeting": update_meeting,
        "insert_brief": insert_brief,
    }.items():
        monkeypatch.setattr(db, name, fn)
    return {"meetings": meetings, "briefs": briefs}


@pytest.fixture
def client():
    return TestClient(app)


BODY = {
    "meeting_url": "https://meet.google.com/abc-defg-hij",
    "mode": "delegate",
    "brief": "Done: SDK v2. Blocked: rate limit. Do not agree to deadlines.",
    "title": "Q4 API sync",
}


def _assert_signed(url: str, path: str, meeting_id: str):
    parts = urlsplit(url)
    assert f"{parts.scheme}://{parts.netloc}{parts.path}" == f"https://crew.example.com{path}"
    assert parse_qs(parts.query) == {"meeting_id": [meeting_id], "token": ["wh-t"]}


@respx.mock
def test_create_meeting_sends_bot(client, store):
    route = respx.post(f"{RECALL}/api/v1/bot/").mock(
        return_value=httpx.Response(201, json={"id": "bot_123"})
    )
    r = client.post("/meetings", json=BODY, headers=AUTH)
    assert r.status_code == 201, r.text
    data = r.json()
    mock = json.loads((MOCKS / "meeting_create.json").read_text())
    assert set(data) == set(mock)
    assert data["status"] == "joining"
    assert data["platform"] == "google_meet"
    assert data["mode"] == "delegate"
    assert data["title"] == "Q4 API sync"
    assert data["started_at"].endswith("Z")
    mid = data["id"]

    assert route.call_count == 1
    req = route.calls.last.request
    assert req.headers["Authorization"] == "Token rk_test"
    sent = json.loads(req.content)
    _assert_signed(sent["output_media"]["camera"]["config"]["url"], "/agent", mid)
    endpoint = sent["recording_config"]["realtime_endpoints"][0]
    _assert_signed(endpoint["url"], "/webhooks/recall/transcript", mid)
    sent["output_media"]["camera"]["config"]["url"] = "<agent>"
    endpoint["url"] = "<transcript>"
    assert sent == {
        "meeting_url": "https://meet.google.com/abc-defg-hij",
        "bot_name": "Atlas (AI) for Artem",
        "output_media": {"camera": {"kind": "webpage", "config": {"url": "<agent>"}}},
        "variant": {
            "google_meet": "web_4_core",
            "zoom": "web_4_core",
            "microsoft_teams": "web_4_core",
        },
        "recording_config": {
            "transcript": {
                "provider": {
                    "recallai_streaming": {
                        "mode": "prioritize_low_latency",
                        "language_code": "en",
                    }
                }
            },
            "realtime_endpoints": [
                {"type": "webhook", "url": "<transcript>", "events": ["transcript.data"]}
            ],
        },
        "automatic_leave": {"waiting_room_timeout": 600},
    }

    assert store["meetings"][mid]["recall_bot_id"] == "bot_123"
    assert store["meetings"][mid]["status"] == "joining"
    assert store["briefs"] == [(mid, BODY["brief"])]


@respx.mock
def test_create_notetaker_skips_brief_and_detects_platform(client, store):
    respx.post(f"{RECALL}/api/v1/bot/").mock(return_value=httpx.Response(201, json={"id": "b"}))
    r = client.post(
        "/meetings",
        json={"meeting_url": "https://us02web.zoom.us/j/123", "mode": "notetaker", "brief": "x"},
        headers=AUTH,
    )
    assert r.status_code == 201
    assert r.json()["platform"] == "zoom"
    assert store["briefs"] == []


@respx.mock
def test_create_meeting_recall_error_marks_failed(client, store):
    respx.post(f"{RECALL}/api/v1/bot/").mock(return_value=httpx.Response(400, json={"x": 1}))
    r = client.post("/meetings", json=BODY, headers=AUTH)
    assert r.status_code == 502
    assert r.json()["error"]["code"] == "upstream_error"
    (m,) = store["meetings"].values()
    assert m["status"] == "failed"


def test_create_meeting_bad_url(client, store):
    r = client.post("/meetings", json={"meeting_url": "https://example.com/x"}, headers=AUTH)
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "bad_request"
    assert store["meetings"] == {}


@pytest.mark.parametrize(
    "headers", [{}, {"Authorization": "Bearer wrong"}, {"Authorization": "demo-t"}]
)
def test_requires_bearer(client, store, headers):
    r = client.post("/meetings", json=BODY, headers=headers)
    assert r.status_code == 401
    assert r.json() == {"error": {"code": "unauthorized", "message": "Missing or invalid token"}}
    assert client.post("/meetings/m_01/leave", headers=headers).status_code == 401


def test_validation_error_format(client, store):
    r = client.post("/meetings", json={"mode": "delegate"}, headers=AUTH)
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "validation_error"


@respx.mock
def test_leave_calls_recall(client, store):
    store["meetings"]["m_01"] = {"id": "m_01", "recall_bot_id": "bot_9", "status": "in_call"}
    route = respx.post(f"{RECALL}/api/v1/bot/bot_9/leave_call/").mock(
        return_value=httpx.Response(200, json={})
    )
    r = client.post("/meetings/m_01/leave", headers=AUTH)
    assert r.status_code == 200
    assert r.json() == json.loads((MOCKS / "meeting_leave.json").read_text())
    assert route.call_count == 1
    assert route.calls.last.request.headers["Authorization"] == "Token rk_test"
    assert store["meetings"]["m_01"]["status"] == "in_call"  # flips on bot.done (M1.3)


@respx.mock
def test_leave_recall_error(client, store):
    store["meetings"]["m_01"] = {"id": "m_01", "recall_bot_id": "bot_9", "status": "in_call"}
    respx.post(f"{RECALL}/api/v1/bot/bot_9/leave_call/").mock(return_value=httpx.Response(500))
    r = client.post("/meetings/m_01/leave", headers=AUTH)
    assert r.status_code == 502
    assert r.json()["error"]["code"] == "upstream_error"


def test_leave_unknown_meeting(client, store):
    r = client.post("/meetings/m_99/leave", headers=AUTH)
    assert r.status_code == 404
    assert r.json() == {"error": {"code": "not_found", "message": "Meeting m_99 not found"}}


def test_health_without_database_url():
    with TestClient(app) as c:  # runs lifespan with empty DATABASE_URL
        assert c.get("/health").json() == {"status": "ok"}

import time

import pytest
from fastapi.testclient import TestClient

from app import db, hub, webhooks_recall
from app.config import get_settings
from app.main import app

URL = "/webhooks/recall/status?token=wh-t"


@pytest.fixture(autouse=True)
def env(monkeypatch):
    for k, v in {"WEBHOOK_TOKEN": "wh-t", "DEMO_TOKEN": "demo-t", "DATABASE_URL": ""}.items():
        monkeypatch.setenv(k, v)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def store(monkeypatch):
    m = {"id": "m_01", "status": "scheduled", "started_at": None, "ended_at": None}
    events, hooks = [], []

    async def by_bot(bot_id):
        return dict(m) if bot_id == "bot_1" else None

    async def update(mid, **fields):
        m.update(fields)
        return dict(m)

    async def publish(mid, type_, data):
        events.append((mid, type_, data))
        return 0

    async def hook(mid):
        hooks.append(mid)

    monkeypatch.setattr(db, "get_meeting_by_bot", by_bot)
    monkeypatch.setattr(db, "update_meeting", update)
    monkeypatch.setattr(hub, "publish", publish)
    monkeypatch.setattr(webhooks_recall, "postcall_hook", hook)
    return {"m": m, "events": events, "hooks": hooks}


def ev(name, bot="bot_1"):
    return {"event": name, "data": {"data": {"code": name[4:]}, "bot": {"id": bot}}}


def send(client, name, bot="bot_1", url=URL):
    r = client.post(url, json=ev(name, bot))
    end = time.monotonic() + 2
    while webhooks_recall._tasks and time.monotonic() < end:
        time.sleep(0.01)
    return r


def test_full_sequence(store):
    c = TestClient(app)
    for name in [
        "bot.joining_call",
        "bot.in_waiting_room",
        "bot.in_call_recording",
        "bot.call_ended",
        "bot.done",
    ]:
        assert send(c, name).status_code == 200
    assert [e[2]["status"] for e in store["events"]] == ["joining", "in_call", "done"]
    assert all(e[1] == "meeting_status" for e in store["events"])
    assert store["m"]["status"] == "done"
    assert store["m"]["started_at"] and store["m"]["ended_at"]
    assert store["hooks"] == ["m_01"]
    send(c, "bot.done")
    send(c, "bot.in_call_recording")
    assert len(store["events"]) == 3 and store["hooks"] == ["m_01"]


def test_fatal_and_unknown_event(store):
    c = TestClient(app)
    send(c, "bot.something_new")
    assert store["events"] == []
    send(c, "bot.fatal")
    assert store["m"]["status"] == "failed"
    assert [e[2]["status"] for e in store["events"]] == ["failed"]


def test_bad_token(store):
    r = send(TestClient(app), "bot.done", url="/webhooks/recall/status?token=nope")
    assert r.status_code == 401 and store["events"] == []


def test_unknown_bot(store):
    r = send(TestClient(app), "bot.done", bot="other")
    assert r.status_code == 200 and store["events"] == [] and store["hooks"] == []

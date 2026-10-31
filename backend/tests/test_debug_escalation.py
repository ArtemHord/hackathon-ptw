"""M3.3b: fake notifier when SLACK_BOT_TOKEN is empty + /debug endpoints."""

import httpx
import pytest

from app import db
from app.config import get_settings
from app.main import app
from tests.test_escalation import MID, env, settle, start, world  # noqa: F401

TOKEN = "wh-t"


@pytest.fixture
def client_env(world, monkeypatch):  # noqa: F811
    monkeypatch.setenv("WEBHOOK_TOKEN", TOKEN)
    monkeypatch.setenv("SLACK_BOT_TOKEN", "")
    get_settings.cache_clear()
    from app.notifier import base as nb
    from app.notifier import fake

    monkeypatch.setitem(nb.NOTIFIERS, "fake", fake.FAKE)

    async def get_escalation(eid):
        r = world["esc"].get(eid)
        return None if r is None else {**r, "expert": "Dima"}

    async def list_escalations(meeting_id=None):
        return [{**r, "expert": "Dima"} for r in world["esc"].values()]

    monkeypatch.setattr(db, "get_escalation", get_escalation, raising=False)
    monkeypatch.setattr(db, "list_escalations", list_escalations, raising=False)
    return world


def client():
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")


async def test_start_uses_fake_notifier_without_token(client_env):
    w = client_env
    res = await start(w)
    row = w["esc"][res["escalation_id"]]
    assert row["external_msg_id"].startswith("fake-")
    assert row["external_channel_id"] == "fake"
    assert w["notifier"].questions == []  # the slack stub was not used


async def test_debug_expert_reply_answers(client_env):
    w = client_env
    res = await start(w)
    async with client() as c:
        r = await c.post(
            f"/debug/expert-reply?token={TOKEN}",
            json={"escalation_id": res["escalation_id"], "text": "Thursday"},
        )
        assert r.status_code == 200
        lst = await c.get(f"/debug/escalations?meeting_id={MID}&token={TOKEN}")
    assert w["esc"][res["escalation_id"]]["status"] == "answered"
    assert any("Thursday" in s for s in w["said"])
    assert [e["type"] for e in w["events"]].count("escalation_answered") == 1
    assert lst.json()[0]["status"] == "answered"


async def test_debug_bad_token_and_unknown_id(client_env):
    async with client() as c:
        r = await c.post("/debug/expert-reply?token=nope", json={"escalation_id": "x", "text": "a"})
        assert r.status_code == 401
        r = await c.get("/debug/escalations?token=nope")
        assert r.status_code == 401
        r = await c.post(
            f"/debug/expert-reply?token={TOKEN}", json={"escalation_id": "nope", "text": "a"}
        )
        assert r.status_code == 404

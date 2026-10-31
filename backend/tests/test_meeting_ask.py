"""M7.1: POST /meetings/{id}/ask (API.pl.md), /debug/* accepting Bearer DEMO_TOKEN,
POST /debug/simulate and app.simulate.drive (respx, no real network)."""

import asyncio
import json
from pathlib import Path

import httpx
import pytest
import respx

from app import agent_voice, db, orchestrator, runtime, simulate
from app.config import get_settings
from app.main import app

ROOT = Path(__file__).resolve().parents[2]
DEMO = "demo-t"
WH = "wh-t"
AUTH = {"Authorization": f"Bearer {DEMO}"}
MID = "m_01"


@pytest.fixture
def world(monkeypatch):
    for k, v in {"DEMO_TOKEN": DEMO, "WEBHOOK_TOKEN": WH, "DATABASE_URL": ""}.items():
        monkeypatch.setenv(k, v)
    get_settings.cache_clear()
    runtime.reset()
    orchestrator._busy.clear()
    w = {
        "meeting": {"id": MID, "mode": "delegate", "status": "in_call"},
        "asked": [],
        "speaking": False,
    }

    async def get_meeting(meeting_id):
        return w["meeting"] if meeting_id == MID else None

    async def get_last_utterances(meeting_id, n=3):
        return [
            {
                "id": "u_1",
                "speaker": "Dima",
                "text": "Atlas, when is the release?",
                "ts_start": 42.6,
            },
            {"id": "u_2", "speaker": "Atlas (AI) for Artem", "text": "Hi", "ts_start": 50.0},
        ]

    async def ask(meeting_id, utterance, question):
        w["asked"].append((meeting_id, utterance, question))
        return True

    async def list_escalations(meeting_id=None):
        return [{"id": "e_1", "status": "waiting", "expert": "Dima"}]

    monkeypatch.setattr(db, "get_meeting", get_meeting)
    monkeypatch.setattr(db, "get_last_utterances", get_last_utterances)
    monkeypatch.setattr(db, "list_escalations", list_escalations)
    monkeypatch.setattr(orchestrator, "ask", ask)
    monkeypatch.setattr(agent_voice, "is_speaking", lambda mid: w["speaking"])
    yield w
    orchestrator._busy.clear()
    get_settings.cache_clear()


def client():
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")


async def settle():
    for _ in range(3):
        await asyncio.sleep(0)


async def test_ask_with_text_matches_mock_shape(world):
    async with client() as c:
        r = await c.post(
            f"/meetings/{MID}/ask",
            headers=AUTH,
            json={"text": "Atlas, when do we migrate to Postgres 17?"},
        )
    assert r.status_code == 202
    mock = json.loads((ROOT / "mocks" / "meeting_ask.json").read_text())
    assert set(r.json()) == set(mock)
    assert r.json() == {
        "id": MID,
        "accepted": True,
        "question": "when do we migrate to Postgres 17?",
    }
    await settle()
    ((mid, utterance, question),) = world["asked"]
    assert mid == MID and question == "when do we migrate to Postgres 17?"
    assert utterance["speaker"] == "Dima" and utterance["ts"] == 42


async def test_ask_without_text_uses_latest_human_line(world):
    async with client() as c:
        r = await c.post(f"/meetings/{MID}/ask", headers=AUTH)
    assert r.status_code == 202 and r.json()["question"] == "when is the release?"


async def test_ask_errors(world):
    async with client() as c:
        unauth = await c.post(f"/meetings/{MID}/ask", json={"text": "x y"})
        missing = await c.post("/meetings/nope/ask", headers=AUTH, json={"text": "x y"})
        world["speaking"] = True
        busy = await c.post(f"/meetings/{MID}/ask", headers=AUTH, json={"text": "x y"})
        world["meeting"]["status"] = "done"
        not_in_call = await c.post(f"/meetings/{MID}/ask", headers=AUTH, json={"text": "x y"})
        world["meeting"]["mode"] = "notetaker"
        not_delegate = await c.post(f"/meetings/{MID}/ask", headers=AUTH, json={"text": "x y"})
    assert unauth.status_code == 401
    assert missing.status_code == 404 and missing.json()["error"]["code"] == "not_found"
    for r, code in ((busy, "busy"), (not_in_call, "not_in_call"), (not_delegate, "not_delegate")):
        assert r.status_code == 409 and r.json()["error"]["code"] == code
    await settle()
    assert world["asked"] == []


async def test_ask_busy_while_answering(world):
    orchestrator._busy.add(MID)
    async with client() as c:
        r = await c.post(f"/meetings/{MID}/ask", headers=AUTH, json={"text": "x y"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "busy"


async def test_debug_accepts_webhook_token_or_demo_bearer(world):
    async with client() as c:
        none = await c.get("/debug/escalations")
        wrong = await c.get("/debug/escalations", headers={"Authorization": f"Bearer {WH}"})
        by_query = await c.get(f"/debug/escalations?token={WH}")
        by_bearer = await c.get("/debug/escalations", headers=AUTH)
    assert none.status_code == 401 and wrong.status_code == 401
    assert none.json()["error"]["code"] == "unauthorized"
    assert by_query.status_code == 200 and by_bearer.status_code == 200
    assert by_bearer.json() == [{"id": "e_1", "status": "waiting", "expert": "Dima"}]


async def test_simulate_needs_db(world):
    async with client() as c:
        r = await c.post("/debug/simulate", headers=AUTH, json={"speed": 20})
    assert r.status_code == 409
    assert r.json() == {"error": {"code": "conflict", "message": "Simulation needs a database"}}


async def test_simulate_starts_run(world, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://fake")
    get_settings.cache_clear()
    calls = []

    async def run(base_url=None, speed=20.0, expert_reply="Thursday"):
        calls.append((speed, expert_reply))
        return "m_sim"

    monkeypatch.setattr(simulate, "run", run)
    async with client() as c:
        r1 = await c.post("/debug/simulate", headers=AUTH, json={"speed": 20, "expert_reply": None})
        r2 = await c.post(f"/debug/simulate?token={WH}")
    assert r1.status_code == 202 and r1.json() == {"meeting_id": "m_sim"}
    assert r2.status_code == 202
    assert calls == [(20.0, None), (20.0, "Thursday")]


@respx.mock
async def test_drive_posts_the_call(monkeypatch):
    monkeypatch.setenv("WEBHOOK_TOKEN", WH)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    get_settings.cache_clear()

    async def no_wait(_s):
        return None

    monkeypatch.setattr(simulate, "_pause", no_wait)
    base = "http://sim.test"
    status = respx.post(f"{base}/webhooks/recall/status").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )
    transcript = respx.post(f"{base}/webhooks/recall/transcript").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )
    respx.get(f"{base}/debug/escalations").mock(
        return_value=httpx.Response(200, json=[{"id": "e_1", "status": "waiting"}])
    )
    reply = respx.post(f"{base}/debug/expert-reply").mock(
        side_effect=[httpx.Response(409, json={}), httpx.Response(200, json={"ok": True})]
    )
    sent = await simulate.drive(base, MID, "sim-bot", speed=1000, expert_reply="Thursday")
    lines = simulate.load_lines()
    assert sent == len(lines)
    assert transcript.call_count == len(lines) + 1  # + the deliberate duplicate
    events = [json.loads(c.request.content)["event"] for c in status.calls]
    assert events == ["bot.joining_call", "bot.in_call_recording", "bot.call_ended", "bot.done"]
    assert all(c.request.url.params["token"] == WH for c in status.calls)
    assert transcript.calls[0].request.url.params["meeting_id"] == MID
    assert reply.call_count == 2
    assert json.loads(reply.calls.last.request.content) == {
        "escalation_id": "e_1",
        "text": "Thursday",
    }
    get_settings.cache_clear()


@respx.mock
async def test_drive_waits_for_agent_and_open_escalation(monkeypatch):
    """speed 20 must not hit "answer in progress"; with no auto reply the call stays live
    until the escalation is answered (web app "Simulate expert reply")."""
    monkeypatch.setenv("WEBHOOK_TOKEN", WH)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    get_settings.cache_clear()
    pauses: list[float] = []

    async def no_wait(s):
        pauses.append(s)

    monkeypatch.setattr(simulate, "_pause", no_wait)
    busy = iter([True, True, True])  # busy for the first 3 checks, then idle
    monkeypatch.setattr(orchestrator, "is_busy", lambda _mid: next(busy, False))
    base = "http://sim.test"
    status = respx.post(f"{base}/webhooks/recall/status").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )
    respx.post(f"{base}/webhooks/recall/transcript").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )
    waiting = httpx.Response(200, json=[{"id": "e_1", "status": "waiting"}])
    answered = httpx.Response(200, json=[{"id": "e_1", "status": "answered"}])
    esc = respx.get(f"{base}/debug/escalations").mock(side_effect=[waiting, waiting, answered])
    reply = respx.post(f"{base}/debug/expert-reply")

    await simulate.drive(base, MID, "sim-bot", speed=1000, expert_reply=None)

    assert pauses.count(0.2) == 3  # held the line while the agent was busy
    assert esc.call_count == 3  # found waiting, polled until answered
    assert not reply.called
    events = [json.loads(c.request.content)["event"] for c in status.calls]
    assert events[-2:] == ["bot.call_ended", "bot.done"]
    get_settings.cache_clear()

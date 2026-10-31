"""M6.3: POST /debug/ask, the stage backup trigger (no wake word needed)."""

import asyncio

import httpx
import pytest

from app import db, orchestrator
from app.config import get_settings
from app.main import app

TOKEN = "wh-t"
MID = "m_01"


@pytest.fixture
def calls(monkeypatch):
    monkeypatch.setenv("WEBHOOK_TOKEN", TOKEN)
    get_settings.cache_clear()
    recorded = []

    async def ask(meeting_id, utterance, question):
        recorded.append((meeting_id, utterance, question))
        return True

    async def get_last_utterances(meeting_id, n=3):
        return [
            {"id": "u_1", "speaker": "Misha", "text": "Morning!", "ts_start": 10.0},
            {
                "id": "u_2",
                "speaker": "Artem",
                "text": "what the tartan finish this week",
                "ts_start": 42.5,
            },
            {"id": "u_3", "speaker": "Call Crew (AI) for Artem", "text": "Hi", "ts_start": 50.0},
            {"id": "u_4", "speaker": "Atlas (AI) for Artem", "text": "Hello", "ts_start": 51.0},
        ]

    monkeypatch.setattr(orchestrator, "ask", ask)
    monkeypatch.setattr(db, "get_last_utterances", get_last_utterances)
    yield recorded
    get_settings.cache_clear()


def client():
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")


async def settle():
    for _ in range(3):
        await asyncio.sleep(0)


async def test_requires_token(calls):
    async with client() as c:
        r1 = await c.post(f"/debug/ask?meeting_id={MID}", json={"text": "status?"})
        r2 = await c.post(f"/debug/ask?meeting_id={MID}&token=nope", json={"text": "x"})
    assert r1.status_code == 401 and r2.status_code == 401
    await settle()
    assert calls == []


async def test_explicit_text_runs_answer_flow(calls):
    async with client() as c:
        r = await c.post(
            f"/debug/ask?meeting_id={MID}&token={TOKEN}",
            json={"text": "What did Artem finish this week?"},
        )
    assert r.status_code == 200
    assert r.json() == {"ok": True, "question": "What did Artem finish this week?"}
    await settle()
    assert len(calls) == 1
    meeting_id, utterance, question = calls[0]
    assert meeting_id == MID and question == "What did Artem finish this week?"
    assert utterance["speaker"] == "Artem" and utterance["ts"] == 42


async def test_explicit_text_strips_wake_word(calls):
    async with client() as c:
        url = f"/debug/ask?meeting_id={MID}&token={TOKEN}"
        r = await c.post(url, json={"text": "Atlas, what is the status?"})
    assert r.json()["question"] == "what is the status?"


async def test_empty_body_uses_last_human_utterance(calls):
    async with client() as c:
        r1 = await c.post(f"/debug/ask?meeting_id={MID}&token={TOKEN}")
        r2 = await c.post(f"/debug/ask?meeting_id={MID}&token={TOKEN}", json={})
    for r in (r1, r2):
        assert r.status_code == 200
        assert r.json() == {"ok": True, "question": "what the tartan finish this week"}
    await settle()
    assert [q for _, _, q in calls] == ["what the tartan finish this week"] * 2
    assert calls[0][1]["speaker"] == "Artem"


async def test_no_utterances_is_404(calls, monkeypatch):
    async def none(meeting_id, n=3):
        return []

    monkeypatch.setattr(db, "get_last_utterances", none)
    async with client() as c:
        r = await c.post(f"/debug/ask?meeting_id={MID}&token={TOKEN}")
    assert r.status_code == 404

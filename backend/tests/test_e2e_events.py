"""M6.1: every WS event of docs/API.pl.md arrives on /app/ws end to end, plus CORS.

Real local Postgres (default port 55450):
`docker run -d -p 55450:5432 -e POSTGRES_PASSWORD=pw pgvector/pgvector:pg16`.
OpenAI is mocked with respx (routed by the strict-schema name), TTS / voice / Recall chat patched.
"""

import asyncio
import json
import os
import threading
import time
from pathlib import Path
from unittest.mock import AsyncMock
from urllib.parse import urlsplit

import asyncpg
import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from app import agent_voice, db, escalation, postcall, recall, tts
from app.config import get_settings
from app.main import app

ROOT = Path(__file__).resolve().parents[2]
MOCKS = ROOT / "mocks"
MIGRATION = ROOT / "backend" / "migrations" / "001_init.sql"
FIXTURE = ROOT / "backend" / "seed" / "demo_transcript.json"
URL = os.environ.get("E2E_DATABASE_URL", "postgresql://postgres:pw@localhost:55450/postgres")
# SAFETY: the fixture drops the public schema; never run against a non-local DB.
if urlsplit(URL).hostname not in ("localhost", "127.0.0.1"):
    pytest.skip("E2E_DATABASE_URL must be localhost", allow_module_level=True)

MID, BOT, WH, DEMO = "m_e2e", "bot-e2e", "wh-t", "demo-t"
OPENAI = "https://api.openai.com/v1"
ENVELOPE = {"type", "meeting_id", "ts", "data"}


def _reachable() -> bool:
    async def go():
        c = await asyncpg.connect(URL, timeout=2)
        await c.close()

    try:
        asyncio.run(go())
        return True
    except Exception:
        return False


needs_db = pytest.mark.skipif(not _reachable(), reason="no test Postgres on 55450")


def _answer(text, needs_expert=False, topic=""):
    return {"answer": text, "confidence": 0.9, "needs_expert": needs_expert, "topic": topic}


def _chat_handler(request: httpx.Request) -> httpx.Response:
    body = json.loads(request.content)
    kind = body["response_format"]["json_schema"]["name"]
    prompt = body["messages"][-1]["content"]
    if kind == "agent_answer":
        if "Postgres 17" in prompt:
            out = _answer("", True, "postgres")
        elif "auth tokens" in prompt:
            out = _answer("", True, "auth")
        else:
            out = _answer("Artem finished the Slack escalation flow.")
    elif kind == "fact_check":
        hit = "100 requests" in prompt
        out = {
            "claim": "limit is 100 rps" if hit else None,
            "verdict": "contradicted" if hit else "unknown",
            "confidence": 0.9 if hit else 0.0,
            "source_title": "api.md" if hit else None,
            "correction": "50 rps" if hit else None,
            "chat_message": "Heads-up: api.md says 50 rps, not 100." if hit else None,
            "old_text": None,
            "new_text": None,
        }
    elif kind == "postcall":
        out = {
            "summary": "Stand-up: API limit and Postgres 17 migration.",
            "decisions": [],
            "action_items": [],
            "facts": [],
        }
    else:
        return httpx.Response(500, json={"error": kind})
    msg = {"role": "assistant", "content": json.dumps(out)}
    return httpx.Response(200, json={"choices": [{"message": msg}]})


@pytest.fixture
def world(monkeypatch):
    for k, v in {
        "DEMO_TOKEN": DEMO,
        "WEBHOOK_TOKEN": WH,
        "DATABASE_URL": URL,
        "OPENAI_API_KEY": "sk-test",
        "OPENAI_CHAT_MODEL": "m",
        "SLACK_BOT_TOKEN": "",
    }.items():
        monkeypatch.setenv(k, v)
    get_settings.cache_clear()
    db._pool = None  # noqa: SLF001
    escalation._cache = None  # noqa: SLF001
    postcall._locks.clear()

    async def seed():
        c = await asyncpg.connect(URL)
        await c.execute("drop schema public cascade; create schema public;")
        await c.execute(MIGRATION.read_text())
        await c.execute(
            """insert into meetings (id,title,platform,mode,status,recall_bot_id,started_at)
               values ($1,'E2E stand-up','google_meet','delegate','joining',$2, now())""",
            MID,
            BOT,
        )
        await c.close()

    asyncio.run(seed())
    from app.notifier import base as nb
    from app.notifier import fake

    monkeypatch.setitem(nb.NOTIFIERS, "fake", fake.FAKE)
    monkeypatch.setattr(escalation, "ESCALATION_TIMEOUT_S", 8.0)
    monkeypatch.setattr(tts, "synthesize", AsyncMock(return_value=b"mp3"))
    monkeypatch.setattr(agent_voice, "play", AsyncMock(return_value=True))
    chat = AsyncMock(return_value=True)
    monkeypatch.setattr(recall, "send_chat_message", chat)
    with respx.mock(assert_all_called=False) as r:
        r.post(f"{OPENAI}/chat/completions").mock(side_effect=_chat_handler)
        r.post(f"{OPENAI}/embeddings").respond(500)  # rag falls back to the seed docs
        yield {"chat": chat}
    get_settings.cache_clear()


def _words(line):
    return [
        {
            "text": w,
            "start_timestamp": {"relative": line["at_s"] + i * 0.3},
            "end_timestamp": {"relative": line["at_s"] + i * 0.3 + 0.25},
        }
        for i, w in enumerate(line["text"].split())
    ]


def _transcript(line):
    data = {"words": _words(line), "participant": {"id": 1, "name": line["speaker"]}}
    return {"event": "transcript.data", "data": {"data": data, "bot": {"id": BOT}}}


def _status(event):
    return {"event": event, "data": {"bot": {"id": BOT}, "data": {"code": event}}}


class Feed:
    """Reads /app/ws events until a predicate holds; a watchdog closes the socket on a hang."""

    def __init__(self, ws):
        self.ws, self.events = ws, []

    def until(self, pred, what, timeout=20.0):
        timer = threading.Timer(timeout, self.ws.close)
        timer.start()
        try:
            while not pred(self.events):
                self.events.append(self.ws.receive_json())
        except Exception as e:
            types = [x["type"] for x in self.events]
            raise AssertionError(f"timed out waiting for {what}; got {types}") from e
        finally:
            timer.cancel()

    def count(self, type_, status=None):
        return sum(
            1
            for e in self.events
            if e["type"] == type_ and (status is None or e["data"].get("status") == status)
        )


def _mock_keys(name):
    return set(json.loads((MOCKS / name).read_text())["data"])


@needs_db
def test_all_seven_ws_events_end_to_end(world):
    lines = json.loads(FIXTURE.read_text())
    with TestClient(app) as c:
        with c.websocket_connect(f"/app/ws?meeting_id={MID}&token={DEMO}") as ws:
            feed = Feed(ws)
            tr = f"/webhooks/recall/transcript?meeting_id={MID}&token={WH}"
            st = f"/webhooks/recall/status?token={WH}"

            assert c.post(st, json=_status("bot.in_call_recording")).status_code == 200
            feed.until(lambda ev: feed.count("meeting_status", "in_call"), "meeting_status")

            for i, line in enumerate(lines):
                assert c.post(tr, json=_transcript(line)).status_code == 200
                n = i + 1
                feed.until(lambda ev, n=n: feed.count("utterance") >= n, f"utterance {n}")
                if line["text"].startswith("Atlas"):
                    said = feed.count("agent_said") + 1
                    feed.until(lambda ev, s=said: feed.count("agent_said") >= s, "agent_said")
                if "Postgres 17" in line["text"]:
                    feed.until(lambda ev: feed.count("escalation_created") >= 1, "escalation")
                    # the fake notifier delivers in a background task: retry until the 409 clears
                    esc_id = next(e for e in feed.events if e["type"] == "escalation_created")[
                        "data"
                    ]["id"]
                    for _ in range(50):
                        r = c.post(
                            f"/debug/expert-reply?token={WH}",
                            json={"escalation_id": esc_id, "text": "Thursday"},
                        )
                        if r.status_code != 409:
                            break
                        time.sleep(0.1)
                    assert r.status_code == 200, r.text
                    feed.until(
                        lambda ev: feed.count("escalation_answered", "answered") >= 1, "answered"
                    )
                    feed.until(lambda ev: feed.count("agent_said") >= 3, "expert agent_said")

            feed.until(lambda ev: feed.count("fact_check") >= 1, "fact_check")
            feed.until(
                lambda ev: feed.count("escalation_answered", "timeout") >= 1, "timeout", 30.0
            )

            assert c.post(st, json=_status("bot.done")).status_code == 200
            feed.until(lambda ev: feed.count("meeting_ended") >= 1, "meeting_ended")
            events = feed.events

    types = {e["type"] for e in events}
    assert types == {
        "utterance",
        "meeting_status",
        "fact_check",
        "escalation_created",
        "escalation_answered",
        "agent_said",
        "meeting_ended",
    }
    for e in events:
        assert set(e) == ENVELOPE, e
        assert e["meeting_id"] == MID
    by_type = {t: [e for e in events if e["type"] == t] for t in types}
    for t, mock in {
        "utterance": "ws_utterance.json",
        "meeting_status": "ws_meeting_status.json",
        "fact_check": "ws_fact_check.json",
        "escalation_created": "ws_escalation_created.json",
        "agent_said": "ws_agent_said.json",
        "meeting_ended": "ws_meeting_ended.json",
    }.items():
        for e in by_type[t]:
            assert set(e["data"]) == _mock_keys(mock), (t, e["data"])
    answered = {e["data"]["status"]: e for e in by_type["escalation_answered"]}
    assert set(answered) == {"answered", "timeout"}
    assert set(answered["answered"]["data"]) == _mock_keys("ws_escalation_answered.json")
    assert set(answered["timeout"]["data"]) == _mock_keys("ws_escalation_timeout.json")
    assert answered["answered"]["data"]["answer"] == "Thursday"
    assert answered["timeout"]["data"]["answer"] is None
    assert any("Thursday" in e["data"]["text"] for e in by_type["agent_said"])
    assert {e["data"]["status"] for e in by_type["meeting_status"]} == {"in_call", "done"}
    world["chat"].assert_any_call(BOT, "Heads-up: api.md says 50 rps, not 100.")


def test_cors_preflight_allows_any_origin():
    with TestClient(app) as c:
        r = c.options(
            "/meetings",
            headers={
                "Origin": "https://app.example.com",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "Authorization, Content-Type",
            },
        )
    assert r.status_code == 200
    assert r.headers["access-control-allow-origin"] == "*"
    assert "POST" in r.headers["access-control-allow-methods"]
    assert "access-control-allow-credentials" not in r.headers


def test_cors_does_not_relax_bearer_auth(monkeypatch):
    monkeypatch.setenv("DEMO_TOKEN", DEMO)
    get_settings.cache_clear()
    with TestClient(app) as c:
        r = c.get("/meetings", headers={"Origin": "https://evil.example"})
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "unauthorized"
    assert r.headers["access-control-allow-origin"] == "*"

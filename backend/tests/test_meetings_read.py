"""GET /meetings and GET /meetings/{id}?since= against a real pgvector DB.

Needs Postgres: TEST_DATABASE_URL (default postgresql://postgres:pw@localhost:55443/postgres),
e.g. `docker run -d -p 55443:5432 -e POSTGRES_PASSWORD=pw pgvector/pgvector:pg16`.
"""

import asyncio
import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit

import asyncpg
import pytest
from fastapi.testclient import TestClient

from app import db
from app.config import get_settings
from app.main import app

MOCKS = Path(__file__).resolve().parents[2] / "mocks"
MIGRATION = Path(__file__).resolve().parents[1] / "migrations" / "001_init.sql"
MIGRATION_SETTINGS = Path(__file__).resolve().parents[1] / "migrations" / "002_settings.sql"
URL = os.environ.get("TEST_DATABASE_URL", "postgresql://postgres:pw@localhost:55443/postgres")
# SAFETY: the fixture drops the public schema; never run against a non-local DB.
if urlsplit(URL).hostname not in ("localhost", "127.0.0.1"):
    pytest.skip("TEST_DATABASE_URL must be localhost", allow_module_level=True)
AUTH = {"Authorization": "Bearer demo-t"}


def _reachable() -> bool:
    async def go():
        c = await asyncpg.connect(URL, timeout=2)
        await c.close()

    try:
        asyncio.run(go())
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _reachable(), reason="no test Postgres")


def keyset(o):
    """Recursive key set; for lists, the union of item key sets."""
    if isinstance(o, dict):
        return {k: keyset(v) for k, v in o.items()}
    if isinstance(o, list):
        merged: dict = {}
        for it in o:
            if isinstance(it, dict):
                merged.update(keyset(it))
        return merged or None
    return None


@pytest.fixture
def client(monkeypatch):
    for k, v in {"DEMO_TOKEN": "demo-t", "DATABASE_URL": URL}.items():
        monkeypatch.setenv(k, v)
    get_settings.cache_clear()
    db._pool = None  # noqa: SLF001

    async def seed():
        c = await asyncpg.connect(URL)
        await c.execute("drop schema public cascade; create schema public;")
        await c.execute(MIGRATION.read_text())
        await c.execute(MIGRATION_SETTINGS.read_text())
        t0 = datetime(2026, 10, 31, 9, 0, tzinfo=UTC)
        await c.execute(
            """insert into meetings (id,title,platform,mode,status,started_at,ended_at,summary,
                 decisions,action_items) values
               ('m_01','Q4 API sync','google_meet','delegate','done',$1,$2,'Raise limit.',
                '["Rate limit -> 100 rps"]'::jsonb,
                '[{"owner":"Artem","text":"Update SDK docs","due":"2026-11-03"}]'::jsonb)""",
            t0,
            t0 + timedelta(minutes=23),
        )
        await c.execute(
            "insert into meetings (id,title,platform,mode,status,started_at) values "
            "('m_02','Standup','zoom','notetaker','in_call',$1)",
            t0 + timedelta(hours=2),
        )
        await c.execute("insert into experts (id,name) values ('x1','Dima')")
        for i, (sp, tx, ts) in enumerate(
            [("Julian", "Atlas, what is our API limit?", 305), ("Dima", "Yes, 15 min TTL", 380)]
        ):
            await c.execute(
                "insert into utterances (id,meeting_id,speaker,text,ts_start) "
                "values ($1,'m_01',$2,$3,$4)",
                f"u_{i}",
                sp,
                tx,
                float(ts),
            )
        await c.execute("insert into kb_docs (id,title) values ('d1','api.md')")
        await c.execute("insert into kb_chunks (id,doc_id,text) values ('c1','d1','50 rps')")
        await c.execute("insert into kb_update_proposals (id,meeting_id) values ('kp_01','m_01')")
        await c.execute(
            """insert into fact_checks (id,meeting_id,claim,verdict,kb_chunk_id,proposal_id,
                 correction,ts) values ('fc_01','m_01','limit is 100 rps','contradicted','c1',
                 'kp_01','50 rps',312.4)"""
        )
        await c.execute(
            """insert into escalations (id,meeting_id,expert_id,question,asked_by,ts,answer,
                 status,answered_ts) values ('esc_01','m_01','x1','Can we cache auth tokens?',
                 'Julian',340,'Yes, 15 min TTL','answered',380)"""
        )
        await c.execute(
            "insert into agent_said (id,meeting_id,text,ts,in_reply_to) values "
            "('as_01','m_01','Dima says: Yes, 15 min TTL.',382,'esc_01')"
        )
        await c.close()

    asyncio.run(seed())
    with TestClient(app) as c:
        yield c
    asyncio.run(db.close_pool())
    db._pool = None  # noqa: SLF001
    get_settings.cache_clear()


def test_list_matches_mock(client):
    r = client.get("/meetings", headers=AUTH)
    assert r.status_code == 200
    body = r.json()
    assert keyset(body) == keyset(json.loads((MOCKS / "meetings_list.json").read_text()))
    assert [i["id"] for i in body["items"]] == ["m_02", "m_01"]
    live, done = body["items"]
    assert live["live"] is True and live["duration_min"] is None
    assert done["live"] is False and done["duration_min"] == 23
    assert done["started_at"] == "2026-10-31T09:00:00Z"


def test_detail_matches_mock(client):
    r = client.get("/meetings/m_01", headers=AUTH)
    assert r.status_code == 200
    body = r.json()
    assert keyset(body) == keyset(json.loads((MOCKS / "meeting_detail.json").read_text()))
    assert body["fact_checks"][0]["source"] == "api.md"
    assert body["fact_checks"][0]["ts"] == 312
    assert body["action_items"][0]["id"] and body["decisions"] == ["Rate limit -> 100 rps"]
    assert [u["ts"] for u in body["utterances"]] == [305, 380]
    assert body["escalations"][0]["expert"] == "Dima"
    assert body["agent_said"][0]["in_reply_to"] == "esc_01"


def test_detail_empty_meeting_has_all_keys(client):
    body = client.get("/meetings/m_02", headers=AUTH).json()
    full = keyset(json.loads((MOCKS / "meeting_detail.json").read_text()))
    assert set(body) == set(full)
    for k in ("decisions", "action_items", "fact_checks", "escalations", "utterances"):
        assert body[k] == []
    assert body["summary"] == "" and body["duration_min"] is None


def test_since_filters(client):
    b = client.get("/meetings/m_01?since=340", headers=AUTH).json()
    assert [u["ts"] for u in b["utterances"]] == [380]
    assert b["fact_checks"] == []
    assert [a["id"] for a in b["agent_said"]] == ["as_01"]
    # escalation asked at 340 but answered at 380 > 340 -> status change shows up
    assert [e["id"] for e in b["escalations"]] == ["esc_01"]
    b = client.get("/meetings/m_01?since=380", headers=AUTH).json()
    assert b["utterances"] == [] and b["escalations"] == []
    assert b["summary"] == "Raise limit."  # scalars always current
    assert [a["id"] for a in b["agent_said"]] == ["as_01"]


def test_auth_and_404(client):
    assert client.get("/meetings").status_code == 401
    assert client.get("/meetings/m_01").status_code == 401
    r = client.get("/meetings/nope", headers=AUTH)
    assert r.status_code == 404
    assert r.json() == {"error": {"code": "not_found", "message": "Meeting nope not found"}}

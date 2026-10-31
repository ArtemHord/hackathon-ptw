"""KB update proposals (M5.2) against a real pgvector DB; OpenAI and Recall are mocked.

Needs Postgres: TEST_DATABASE_URL (default postgresql://postgres:pw@localhost:55449/postgres),
e.g. `docker run -d -p 55449:5432 -e POSTGRES_PASSWORD=pw pgvector/pgvector:pg16`.
"""

import asyncio
import json
import os
from pathlib import Path
from urllib.parse import urlsplit

import asyncpg
import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from app import db, factcheck, hub, rag, recall
from app.config import get_settings
from app.main import app

MOCKS = Path(__file__).resolve().parents[2] / "mocks"
MIGRATION = Path(__file__).resolve().parents[1] / "migrations" / "001_init.sql"
URL = os.environ.get("TEST_DATABASE_URL", "postgresql://postgres:pw@localhost:55449/postgres")
# SAFETY: the fixture drops the public schema; never run against a non-local DB.
if urlsplit(URL).hostname not in ("localhost", "127.0.0.1"):
    pytest.skip("TEST_DATABASE_URL must be localhost", allow_module_level=True)
AUTH = {"Authorization": "Bearer demo-t"}
OPENAI = "https://api.openai.com/v1/chat/completions"
EMBED = "https://api.openai.com/v1/embeddings"
OLD = "Rate limit: 50 rps per key."
NEW = "Rate limit: 100 rps per key (from Monday)."
LINE = {"id": None, "speaker": "Julian", "text": "From Monday the limit is 100 rps", "ts": 312}


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


def run(sql: str, *args):
    async def go():
        c = await asyncpg.connect(URL)
        try:
            return await c.fetch(sql, *args)
        finally:
            await c.close()

    return asyncio.run(go())


@pytest.fixture
def client(monkeypatch):
    for k, v in {
        "DEMO_TOKEN": "demo-t",
        "DATABASE_URL": URL,
        "OPENAI_API_KEY": "sk-test",
        "OPENAI_CHAT_MODEL": "m",
        "OPENAI_EMBED_MODEL": "e",
    }.items():
        monkeypatch.setenv(k, v)
    get_settings.cache_clear()
    db._pool = None  # noqa: SLF001
    factcheck._last_post.clear()  # noqa: SLF001

    async def seed():
        c = await asyncpg.connect(URL)
        await c.execute("drop schema public cascade; create schema public;")
        await c.execute(MIGRATION.read_text())
        await c.execute(
            "insert into meetings (id,title,platform,mode,status,recall_bot_id) values "
            "('m_01','Q4','google_meet','delegate','in_call','bot1')"
        )
        await c.execute("insert into kb_docs (id,title,version) values ('kb_01','api.md',2)")
        await c.execute(
            "insert into kb_chunks (id,doc_id,text,version) values ('c1','kb_01',$1,2)",
            f"# API\n\n{OLD}\nTokens expire after 15 min.",
        )
        await c.close()

    asyncio.run(seed())
    with TestClient(app) as c:
        yield c
    asyncio.run(db.close_pool())
    db._pool = None  # noqa: SLF001
    get_settings.cache_clear()


@pytest.fixture
def chats(monkeypatch):
    class Sent(list):
        events: list

    sent = Sent()

    async def send(bot_id, text):
        sent.append((bot_id, text))
        return True

    async def search(*a, **k):
        return [{"kind": "kb", "text": OLD, "score": 0.9, "doc_title": "api.md"}]

    events: list = []
    sent.events = events

    async def publish(mid, type_, data):
        events.append((type_, data))
        return 1

    monkeypatch.setattr(recall, "send_chat_message", send)
    monkeypatch.setattr(rag, "search", search)
    monkeypatch.setattr(hub, "publish", publish)
    return sent


def llm_reply(verdict="change", confidence=0.9, old_text=OLD, new_text=NEW):
    content = {
        "claim": "limit will be 100 rps",
        "verdict": verdict,
        "confidence": confidence,
        "source_title": "api.md",
        "correction": None,
        "chat_message": None,
        "old_text": old_text,
        "new_text": new_text,
    }
    return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(content)}}]})


def make_proposal(client, chats, **kw) -> str:
    with respx.mock() as m:
        m.post(OPENAI).mock(return_value=llm_reply(**kw))
        client.portal.call(factcheck.check, "m_01", LINE)
    rows = run("select id from kb_update_proposals")
    return rows[0]["id"] if rows else ""


def embed_ok(m):
    return m.post(EMBED).mock(
        return_value=httpx.Response(200, json={"data": [{"index": 0, "embedding": [0.1] * 1536}]})
    )


def test_change_creates_proposal_and_fact_check(client, chats):
    pid = make_proposal(client, chats)
    assert pid
    p = run("select * from kb_update_proposals")[0]
    assert (p["doc_id"], p["chunk_id"], p["status"]) == ("kb_01", "c1", "pending")
    assert (p["old_text"], p["new_text"], p["speaker"], p["ts"]) == (OLD, NEW, "Julian", 312)
    fc = run("select verdict, proposal_id, posted from fact_checks")[0]
    assert (fc["verdict"], fc["proposal_id"], fc["posted"]) == ("unverified", pid, True)
    assert chats[0][0] == "bot1"
    assert chats[0][1].startswith("Noted: Rate limit: 100 rps") and "api.md" in chats[0][1]
    assert chats.events[0][1]["proposal_id"] == pid
    assert chats.events[0][1]["verdict"] == "unverified"


def test_change_low_confidence_or_unmatched_makes_no_proposal(client, chats):
    assert make_proposal(client, chats, confidence=0.6) == ""
    assert make_proposal(client, chats, old_text="Not in the doc.") == ""
    assert chats == []
    assert chats.events[0][1]["proposal_id"] is None


def test_list_matches_mock_and_pending_first(client, chats):
    pid = make_proposal(client, chats)
    run(
        "insert into kb_update_proposals (id,meeting_id,doc_id,status) "
        "values ('old','m_01','kb_01','rejected')"
    )
    assert client.get("/kb/proposals").status_code == 401
    body = client.get("/kb/proposals", headers=AUTH).json()
    mock = json.loads((MOCKS / "kb_proposals.json").read_text())
    assert [i["id"] for i in body["items"]] == [pid]
    assert set(body["items"][0]) == set(mock["items"][0])
    assert body["items"][0]["doc_title"] == "api.md" and body["items"][0]["ts"] == 312
    allp = client.get("/kb/proposals?status=all", headers=AUTH).json()["items"]
    assert [i["id"] for i in allp] == [pid, "old"]


def test_approve_updates_chunk_bumps_versions(client, chats):
    pid = make_proposal(client, chats)
    assert client.post(f"/kb/proposals/{pid}/approve").status_code == 401
    with respx.mock() as m:
        route = embed_ok(m)
        r = client.post(f"/kb/proposals/{pid}/approve", headers=AUTH)
        assert route.called
    assert r.status_code == 200
    assert r.json() == {"id": pid, "status": "approved", "doc_id": "kb_01", "doc_version": 3}
    assert set(r.json()) == set(json.loads((MOCKS / "kb_proposal_approve.json").read_text()))
    c = run("select text, version, embedding is not null as emb from kb_chunks where id='c1'")[0]
    assert NEW in c["text"] and OLD not in c["text"] and "Tokens expire" in c["text"]
    assert c["version"] == 3 and c["emb"] is True
    assert run("select version from kb_docs where id='kb_01'")[0]["version"] == 3
    assert run("select status from kb_update_proposals")[0]["status"] == "approved"
    # second approve is not idempotent: 409 conflict
    r2 = client.post(f"/kb/proposals/{pid}/approve", headers=AUTH)
    assert r2.status_code == 409 and r2.json()["error"]["code"] == "conflict"
    assert run("select version from kb_docs where id='kb_01'")[0]["version"] == 3


def test_approve_keeps_text_when_embedding_fails(client, chats):
    pid = make_proposal(client, chats)
    with respx.mock() as m:
        m.post(EMBED).mock(return_value=httpx.Response(500, text="boom"))
        r = client.post(f"/kb/proposals/{pid}/approve", headers=AUTH)
    assert r.status_code == 200
    assert NEW in run("select text from kb_chunks where id='c1'")[0]["text"]


def test_approve_409_when_old_text_gone(client, chats):
    pid = make_proposal(client, chats)
    run("update kb_chunks set text = 'rewritten' where id = 'c1'")
    r = client.post(f"/kb/proposals/{pid}/approve", headers=AUTH)
    assert r.status_code == 409 and r.json()["error"]["code"] == "conflict"
    assert run("select status from kb_update_proposals")[0]["status"] == "pending"
    assert client.post("/kb/proposals/nope/approve", headers=AUTH).status_code == 404


def test_reject_leaves_kb_untouched(client, chats):
    pid = make_proposal(client, chats)
    assert client.post(f"/kb/proposals/{pid}/reject").status_code == 401
    r = client.post(f"/kb/proposals/{pid}/reject", headers=AUTH)
    assert r.status_code == 200
    assert r.json() == {"id": pid, "status": "rejected", "doc_id": "kb_01", "doc_version": None}
    assert OLD in run("select text from kb_chunks where id='c1'")[0]["text"]
    assert run("select version from kb_docs where id='kb_01'")[0]["version"] == 2
    assert client.post(f"/kb/proposals/{pid}/reject", headers=AUTH).status_code == 409
    assert client.post(f"/kb/proposals/{pid}/approve", headers=AUTH).status_code == 409

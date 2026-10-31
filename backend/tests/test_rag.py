"""Knowledge base: chunking (pure), /kb/docs + search against a real pgvector DB.

DB tests need Postgres: TEST_DATABASE_URL (default postgresql://postgres:pw@localhost:55445/postgres),
e.g. `docker run -d -p 55445:5432 -e POSTGRES_PASSWORD=pw pgvector/pgvector:pg16`.
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

from app import db, rag
from app.config import get_settings
from app.main import app

MOCKS = Path(__file__).resolve().parents[2] / "mocks"
MIGRATION = Path(__file__).resolve().parents[1] / "migrations" / "001_init.sql"
MIGRATION_SETTINGS = Path(__file__).resolve().parents[1] / "migrations" / "002_settings.sql"
URL = os.environ.get("TEST_DATABASE_URL", "postgresql://postgres:pw@localhost:55445/postgres")
AUTH = {"Authorization": "Bearer demo-t"}
EMB_URL = "https://api.openai.com/v1/embeddings"


def fake_vec(text: str) -> list[float]:
    """1536-dim: axis 0 = 'rate', axis 1 = 'cache', else axis 2."""
    v = [0.0] * 1536
    v[0 if "rate" in text else 1 if "cache" in text else 2] = 1.0
    return v


def embeddings_handler(request: httpx.Request) -> httpx.Response:
    inputs = json.loads(request.content)["input"]
    data = [{"index": i, "embedding": fake_vec(t)} for i, t in enumerate(inputs)]
    return httpx.Response(200, json={"data": data})


# --- chunking (no DB) --------------------------------------------------------


def test_chunk_sizes_and_overlap():
    paras = [f"P{i} " + ("word " * 200).strip() for i in range(10)]  # ~1000 chars each
    chunks = rag.chunk_text("\n\n".join(paras))
    assert len(chunks) >= 4
    assert all(len(c) <= rag.CHUNK_CHARS for c in chunks)
    for a, b in zip(chunks, chunks[1:], strict=False):
        assert a[-rag.OVERLAP_CHARS :] in b[: rag.OVERLAP_CHARS + 5]
    assert rag.chunk_text("short") == ["short"]
    assert rag.chunk_text("  \n\n ") == []


def test_chunk_hard_splits_giant_paragraph():
    chunks = rag.chunk_text("x" * 7000)
    assert len(chunks) >= 3
    assert all(len(c) <= rag.CHUNK_CHARS for c in chunks)


# --- DB ----------------------------------------------------------------------

if urlsplit(URL).hostname not in ("localhost", "127.0.0.1"):
    pytest.skip("TEST_DATABASE_URL must be localhost", allow_module_level=True)


def _reachable() -> bool:
    async def go():
        c = await asyncpg.connect(URL, timeout=2)
        await c.close()

    try:
        asyncio.run(go())
        return True
    except Exception:
        return False


needs_db = pytest.mark.skipif(not _reachable(), reason="no test Postgres")


@pytest.fixture
def client(monkeypatch):
    for k, v in {
        "DEMO_TOKEN": "demo-t",
        "DATABASE_URL": URL,
        "OPENAI_API_KEY": "sk-test",
        "OPENAI_EMBED_MODEL": "emb-test",
    }.items():
        monkeypatch.setenv(k, v)
    get_settings.cache_clear()
    db._pool = None  # noqa: SLF001

    async def reset():
        c = await asyncpg.connect(URL)
        await c.execute("drop schema public cascade; create schema public;")
        await c.execute(MIGRATION.read_text())
        await c.execute(MIGRATION_SETTINGS.read_text())
        await c.close()

    asyncio.run(reset())
    with respx.mock(assert_all_called=False) as mock:
        mock.post(EMB_URL).mock(side_effect=embeddings_handler)
        with TestClient(app) as c:
            yield c
    get_settings.cache_clear()


def keys(o):
    return set(o)


@needs_db
def test_requires_bearer(client):
    assert client.get("/kb/docs").status_code == 401
    r = client.post("/kb/docs", files={"file": ("a.md", b"hi")})
    assert r.status_code == 401


@needs_db
def test_upload_version_bump_and_shapes(client):
    mock_create = json.loads((MOCKS / "kb_doc_create.json").read_text())
    mock_list = json.loads((MOCKS / "kb_docs.json").read_text())
    r = client.post("/kb/docs", files={"file": ("api.md", b"# API\n\nrate limit")}, headers=AUTH)
    assert r.status_code == 201
    assert keys(r.json()) == keys(mock_create)
    assert r.json()["version"] == 1 and r.json()["chunks"] == 1
    r = client.post("/kb/docs", files={"file": ("api.md", b"# API\n\ncache " * 2)}, headers=AUTH)
    assert r.json()["version"] == 2
    r = client.get("/kb/docs", headers=AUTH)
    items = r.json()["items"]
    assert len(items) == 1  # same title -> same doc
    assert keys(items[0]) == keys(mock_list["items"][0])
    assert keys(items[0]["versions"][0]) == keys(mock_list["items"][0]["versions"][0])
    assert [v["version"] for v in items[0]["versions"]] == [1, 2]
    assert items[0]["chunks"] == 1  # old chunks replaced


@needs_db
def test_search_and_backfill(client):
    client.post("/kb/docs", files={"file": ("api.md", b"rate limit is 50 rps")}, headers=AUTH)
    client.post("/kb/docs", files={"file": ("auth.md", b"cache tokens 15 min")}, headers=AUTH)

    async def go():
        pool = await db.get_pool()
        await pool.execute("insert into meetings (id,title) values ('m1','t')")
        await pool.execute(
            "insert into utterances (id,meeting_id,speaker,text,ts_start) "
            "values ('u1','m1','Dima','we should cache tokens',12)"
        )
        await pool.execute(
            "insert into facts (id,meeting_id,speaker,text,kind) "
            "values ('f1','m1','Dima','rate is 100 rps','number')"
        )
        n = await rag.backfill_embeddings()
        assert n == 2
        assert await rag.backfill_embeddings() == 0
        hits = await rag.search("what is the rate limit", k=6)
        assert {h["kind"] for h in hits} == {"kb", "facts", "utterances"}
        assert hits[0]["score"] >= hits[-1]["score"]
        top = hits[0]
        assert top["score"] == pytest.approx(1.0)
        assert top["kind"] in ("kb", "facts")
        kb_hit = next(h for h in hits if h["kind"] == "kb")
        assert kb_hit["doc_title"] == "api.md"
        utt = next(h for h in hits if h["kind"] == "utterances")
        assert (utt["meeting_id"], utt["speaker"], utt["ts"]) == ("m1", "Dima", 12)
        only = await rag.search("cache?", k=1, kinds=("kb",))
        assert len(only) == 1 and only[0]["doc_title"] == "auth.md"
        await db.close_pool()

    # TestClient runs its own loop; use a fresh pool for this loop
    db._pool = None  # noqa: SLF001
    asyncio.run(go())
    db._pool = None  # noqa: SLF001

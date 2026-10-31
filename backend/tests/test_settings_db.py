"""M7.1 against a real Postgres: app_settings round trip, experts CRUD SQL, seed only when empty.

Needs Postgres: TEST_DATABASE_URL (default postgresql://postgres:pw@localhost:55449/postgres),
e.g. `docker run -d -p 55449:5432 -e POSTGRES_PASSWORD=pw pgvector/pgvector:pg16`.
"""

import asyncio
import os
from pathlib import Path
from urllib.parse import urlsplit

import asyncpg
import pytest
from fastapi.testclient import TestClient

from app import db, escalation, orchestrator, runtime
from app.config import get_settings
from app.main import app

MIGRATIONS = Path(__file__).resolve().parents[1] / "migrations"
URL = os.environ.get("TEST_DATABASE_URL", "postgresql://postgres:pw@localhost:55449/postgres")
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


@pytest.fixture
def client(monkeypatch):
    for k, v in {
        "DEMO_TOKEN": "demo-t",
        "DATABASE_URL": URL,
        "SLACK_BOT_TOKEN": "",
        "AGENT_NAME": "Atlas",
        "OWNER_NAME": "Artem",
    }.items():
        monkeypatch.setenv(k, v)
    get_settings.cache_clear()
    db._pool = None  # noqa: SLF001
    runtime.reset()
    monkeypatch.setattr(escalation, "_cache", None)
    monkeypatch.setattr(orchestrator, "_experts_cache", None)

    async def seed():
        c = await asyncpg.connect(URL)
        await c.execute("drop schema public cascade; create schema public;")
        for f in sorted(MIGRATIONS.glob("*.sql")):
            await c.execute(f.read_text())
        await c.execute("insert into app_settings (key, value) values ('OWNER_NAME', 'Julian')")
        await c.close()

    asyncio.run(seed())
    with TestClient(app) as c:  # lifespan: runtime.load() + seed_experts()
        yield c
    asyncio.run(db.close_pool())
    db._pool = None  # noqa: SLF001
    runtime.reset()
    get_settings.cache_clear()


def test_settings_persist_and_reload(client):
    assert runtime.get("OWNER_NAME") == "Julian"  # loaded at startup
    r = client.put("/settings", headers=AUTH, json={"AGENT_NAME": "Nova", "OWNER_NAME": ""})
    assert r.status_code == 200
    assert r.json()["values"]["OWNER_NAME"]["source"] == "env"

    async def rows():
        return await db.list_settings()

    assert client.portal.call(rows) == {"AGENT_NAME": "Nova"}
    runtime.reset()
    client.portal.call(runtime.load)
    assert runtime.get("AGENT_NAME") == "Nova" and runtime.get("OWNER_NAME") == "Artem"


def test_experts_crud_and_seed_once(client):
    items = client.get("/experts", headers=AUTH).json()["items"]
    assert "Dima" in [e["name"] for e in items]  # seeded into the empty table
    owner = next(e for e in items if e["is_owner"])
    assert owner["name"] == "Artem" and "owner" not in owner["topics"]

    new = client.post(
        "/experts",
        headers=AUTH,
        json={"name": "Olga", "role": "QA", "topics": ["testing"], "channel": "telegram"},
    ).json()
    assert new["id"] and new["channel"] == "telegram"
    upd = client.put(f"/experts/{new['id']}", headers=AUTH, json={"telegram_chat_id": "42"})
    assert upd.json()["telegram_chat_id"] == "42" and upd.json()["topics"] == ["testing"]
    assert "Olga" in [e.name for e in escalation._cache]
    dima = next(e for e in items if e["name"] == "Dima")
    assert client.delete(f"/experts/{dima['id']}", headers=AUTH).json()["deleted"] is True

    async def reseed():
        await escalation.seed_experts()
        return await db.count_experts()

    before = len(items)  # seed size; -1 Dima +1 Olga
    assert client.portal.call(reseed) == before  # not reseeded: table not empty
    names = [e["name"] for e in client.get("/experts", headers=AUTH).json()["items"]]
    assert "Dima" not in names and "Olga" in names

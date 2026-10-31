"""M7.1: experts CRUD + "Send test" (fake DB, respx for Slack)."""

import json

import httpx
import pytest
import respx

from app import db, escalation, orchestrator, runtime
from app.config import get_settings
from app.main import app
from app.notifier.slack import SLACK

DEMO = "demo-t"
AUTH = {"Authorization": f"Bearer {DEMO}"}
SLACK_API = "https://slack.com/api"


class FakeDB:
    """In-memory experts table with the db.py helper signatures."""

    def __init__(self):
        self.rows: dict[str, dict] = {}
        self.n = 0

    @staticmethod
    def _out(r):
        return {**r, "is_owner": "owner" in r["topics"]}

    async def list_experts(self):
        return [self._out(r) for r in self.rows.values()]

    async def get_expert(self, expert_id):
        r = self.rows.get(expert_id)
        return self._out(r) if r else None

    async def insert_expert(self, e):
        self.n += 1
        r = {
            "id": f"ex_{self.n}",
            "name": e["name"],
            "role": e.get("role") or "",
            "topics": list(e.get("topics") or []),
            "channel": e.get("channel") or "slack",
            "email": e.get("email"),
            "slack_user_id": e.get("slack_user_id"),
            "telegram_chat_id": e.get("telegram_chat_id"),
        }
        self.rows[r["id"]] = r
        return self._out(r)

    async def update_expert(self, expert_id, **fields):
        r = self.rows.get(expert_id)
        if r is None:
            return None
        r.update(fields)
        return self._out(r)

    async def delete_expert(self, expert_id):
        return self.rows.pop(expert_id, None) is not None


@pytest.fixture
def fake(monkeypatch):
    for k, v in {
        "DEMO_TOKEN": DEMO,
        "DATABASE_URL": "postgresql://fake",
        "SLACK_BOT_TOKEN": "xoxb-test",
        "AGENT_NAME": "Atlas",
        "OWNER_NAME": "Artem",
    }.items():
        monkeypatch.setenv(k, v)
    get_settings.cache_clear()
    runtime.reset()
    SLACK.reset()
    f = FakeDB()
    for name in ("list_experts", "get_expert", "insert_expert", "update_expert", "delete_expert"):
        monkeypatch.setattr(db, name, getattr(f, name))
    monkeypatch.setattr(escalation, "_cache", None)
    monkeypatch.setattr(orchestrator, "_experts_cache", "stale")
    yield f
    runtime.reset()
    SLACK.reset()
    get_settings.cache_clear()


def client():
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")


DIMA = {
    "name": "Dima",
    "role": "Backend",
    "topics": ["postgres", " infra ", "owner", ""],
    "channel": "slack",
    "email": "dima@example.com",
    "slack_user_id": None,
    "telegram_chat_id": None,
    "is_owner": False,
}


async def test_requires_demo_token(fake):
    async with client() as c:
        r = await c.get("/experts")
        r2 = await c.delete("/experts/ex_1")
    assert r.status_code == 401 and r2.status_code == 401


async def test_crud_roundtrip(fake):
    async with client() as c:
        r = await c.post("/experts", headers=AUTH, json=DIMA)
        assert r.status_code == 201
        dima = r.json()
        assert dima == {
            "id": "ex_1",
            "name": "Dima",
            "role": "Backend",
            "topics": ["postgres", "infra"],
            "channel": "slack",
            "email": "dima@example.com",
            "slack_user_id": None,
            "telegram_chat_id": None,
            "is_owner": False,
            "profile": "acme",
        }
        # caches invalidated: escalation sees the new expert, the prompt list is rebuilt
        assert [e.name for e in escalation._cache] == ["Dima"]
        assert orchestrator._experts_cache is None
        assert await orchestrator.experts_text() == "- Dima: postgres, infra"

        r = await c.post(
            "/experts",
            headers=AUTH,
            json={"name": "Artem", "topics": [], "is_owner": True, "channel": "telegram"},
        )
        assert r.json()["is_owner"] is True and r.json()["topics"] == []
        assert fake.rows["ex_2"]["topics"] == ["owner"]  # stored the db.py way

        r = await c.put(
            "/experts/ex_1", headers=AUTH, json={"topics": ["database"], "slack_user_id": "U1"}
        )
        assert r.status_code == 200
        assert r.json()["topics"] == ["database"] and r.json()["slack_user_id"] == "U1"
        assert r.json()["role"] == "Backend"  # partial update keeps the rest

        r = await c.put("/experts/ex_2", headers=AUTH, json={"topics": ["mobile"]})
        assert r.json()["is_owner"] is True and fake.rows["ex_2"]["topics"] == ["mobile", "owner"]

        items = (await c.get("/experts", headers=AUTH)).json()["items"]
        assert [e["name"] for e in items] == ["Dima", "Artem"]

        r = await c.delete("/experts/ex_1", headers=AUTH)
        assert r.json() == {"id": "ex_1", "deleted": True}
        assert [e.name for e in escalation._cache] == ["Artem"]
        r = await c.delete("/experts/ex_1", headers=AUTH)
        assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"


async def test_validation_and_404(fake):
    async with client() as c:
        r1 = await c.post("/experts", headers=AUTH, json={**DIMA, "name": "  "})
        r2 = await c.post("/experts", headers=AUTH, json={**DIMA, "channel": "email"})
        r3 = await c.put("/experts/nope", headers=AUTH, json={"role": "x"})
        r4 = await c.post("/experts/nope/test", headers=AUTH)
    assert r1.status_code == 422 and r1.json()["error"]["code"] == "validation_error"
    assert r2.status_code == 422
    assert r3.status_code == 404 and r4.status_code == 404


async def test_writes_need_db(fake, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "")
    get_settings.cache_clear()
    async with client() as c:
        r = await c.post("/experts", headers=AUTH, json=DIMA)
        listed = await c.get("/experts", headers=AUTH)
    assert r.status_code == 409 and r.json()["error"]["code"] == "conflict"
    names = [e["name"] for e in listed.json()["items"]]
    assert "Dima" in names and "Artem" in names  # seed file, read-only


@respx.mock
async def test_send_test_via_slack(fake):
    respx.get(f"{SLACK_API}/users.lookupByEmail").mock(
        return_value=httpx.Response(200, json={"ok": True, "user": {"id": "U_DIMA"}})
    )
    respx.post(f"{SLACK_API}/conversations.open").mock(
        return_value=httpx.Response(200, json={"ok": True, "channel": {"id": "D1"}})
    )
    post = respx.post(f"{SLACK_API}/chat.postMessage").mock(
        return_value=httpx.Response(200, json={"ok": True, "ts": "1.2", "channel": "D1"})
    )
    async with client() as c:
        await c.post("/experts", headers=AUTH, json=DIMA)
        r = await c.post("/experts/ex_1/test", headers=AUTH)
    assert r.json() == {"ok": True, "detail": "Test message sent to Dima via slack"}
    sent = json.loads(post.calls.last.request.content)
    assert sent["channel"] == "D1" and sent["text"].startswith("Hi Dima, this is a test message")
    assert "Atlas" in sent["text"]


@respx.mock
async def test_send_test_slack_error_and_fake(fake, monkeypatch):
    respx.get(f"{SLACK_API}/users.lookupByEmail").mock(
        return_value=httpx.Response(200, json={"ok": False, "error": "users_not_found"})
    )
    async with client() as c:
        await c.post("/experts", headers=AUTH, json=DIMA)
        bad = (await c.post("/experts/ex_1/test", headers=AUTH)).json()
        monkeypatch.setenv("SLACK_BOT_TOKEN", "")
        get_settings.cache_clear()
        fake_sent = (await c.post("/experts/ex_1/test", headers=AUTH)).json()
    assert bad == {"ok": False, "detail": "slack users.lookupByEmail: users_not_found"}
    assert fake_sent["ok"] is False and "not configured" in fake_sent["detail"]


async def test_seed_experts_only_when_empty(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://fake")
    get_settings.cache_clear()
    seeded = []

    async def count_experts():
        return 2

    async def upsert_experts(items):
        seeded.append(items)

    rows = [{"name": "Dima", "topics": ["infra"]}, {"name": "Ola", "topics": ["profile:msp"]}]

    async def list_experts():
        return rows

    monkeypatch.setattr(db, "count_experts", count_experts)
    monkeypatch.setattr(db, "upsert_experts", upsert_experts)
    monkeypatch.setattr(db, "list_experts", list_experts)
    monkeypatch.setattr(escalation, "_cache", None)
    await escalation.seed_experts()
    assert seeded == []

    async def count_zero():
        return 0

    monkeypatch.setattr(db, "count_experts", count_zero)
    rows[:] = rows[1:]  # only an msp expert left: acme is seeded again
    await escalation.seed_experts()
    assert len(seeded) == 1 and seeded[0][0]["name"] == "Dima"
    get_settings.cache_clear()


async def test_create_with_null_role(fake):
    """The web form sends null for an empty field (verifier bug: 422 on empty Role)."""
    async with client() as c:
        r = await c.post("/experts", headers=AUTH, json={**DIMA, "role": None})
    assert r.status_code == 201
    assert r.json()["role"] == ""

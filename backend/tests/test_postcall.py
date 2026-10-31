import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from app import db, hub, postcall
from app.config import get_settings
from app.main import app

MOCKS = Path(__file__).resolve().parents[2] / "mocks"
OPENAI = "https://api.openai.com/v1/chat/completions"


@pytest.fixture(autouse=True)
def env(monkeypatch):
    for k, v in {
        "OPENAI_API_KEY": "sk-test",
        "OPENAI_CHAT_MODEL": "m",
        "DEMO_TOKEN": "demo-t",
        "DATABASE_URL": "",
    }.items():
        monkeypatch.setenv(k, v)
    get_settings.cache_clear()
    postcall._locks.clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def store(monkeypatch):
    m = {
        "id": "m_01",
        "summary": "",
        "decisions": [],
        "action_items": [{"owner": "Dima", "text": "Confirm the rollout date", "due": None}],
        "status": "done",
        "recall_bot_id": None,
        "started_at": datetime(2026, 10, 31, 9, 0, tzinfo=UTC),
        "ended_at": datetime(2026, 10, 31, 9, 23, tzinfo=UTC),
    }
    events, facts = [], []

    async def get_meeting(mid):
        return dict(m)

    async def update_meeting(mid, **kw):
        m.update(kw)
        return dict(m)

    async def utts(mid):
        return [{"speaker": "Anna", "text": "Limit goes to 100 rps.", "ts_start": 3.0}]

    async def brief(mid):
        return "Sync on API limits"

    async def escs(mid):
        return [
            {"expert": "Dima", "question": "When is the rollout?", "answer": "Thursday",
             "status": "answered"}
        ]  # fmt: skip

    async def fact(mid, speaker, text, kind):
        facts.append((speaker, text, kind))
        return {}

    async def publish(mid, type_, data):
        events.append((mid, type_, data))
        return 0

    for name, fn in {
        "get_meeting": get_meeting,
        "update_meeting": update_meeting,
        "get_all_utterances": utts,
        "get_brief": brief,
        "list_escalations": escs,
        "insert_fact": fact,
    }.items():
        monkeypatch.setattr(db, name, fn)
    monkeypatch.setattr(hub, "publish", publish)
    return {"m": m, "events": events, "facts": facts}


def llm_reply(**over):
    out = {
        "summary": "Limit raised to 100 rps.",
        "decisions": ["Raise the API limit to 100 rps"],
        "action_items": [
            {"owner": "dima", "text": "confirm the rollout date", "due": None},
            {"owner": "Anna", "text": "Update the docs", "due": "Friday"},
        ],
        "facts": [{"speaker": "Anna", "text": "Limit is 100 rps", "kind": "number"}],
    }
    out.update(over)
    return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(out)}}]})


@respx.mock
async def test_happy_path(store):
    route = respx.post(OPENAI).mock(return_value=llm_reply())
    await postcall.run("m_01")
    m = store["m"]
    assert m["summary"] == "Limit raised to 100 rps."
    assert m["decisions"] == ["Raise the API limit to 100 rps"]
    # timeout item preserved, LLM duplicate (case-insensitive) dropped
    assert [i["text"] for i in m["action_items"]] == [
        "Confirm the rollout date",
        "Update the docs",
    ]
    assert store["facts"] == [("Anna", "Limit is 100 rps", "number")]
    ((mid, type_, data),) = store["events"]
    mock = json.loads((MOCKS / "ws_meeting_ended.json").read_text())
    assert (mid, type_) == (mock["meeting_id"], mock["type"])
    assert data == mock["data"]
    body = json.loads(route.calls.last.request.content)
    assert "Thursday" in body["messages"][1]["content"]
    assert body["response_format"]["json_schema"]["strict"] is True


@respx.mock
async def test_second_run_noop(store):
    route = respx.post(OPENAI).mock(return_value=llm_reply())
    await postcall.run("m_01")
    await postcall.run("m_01")
    assert route.call_count == 1
    assert len(store["events"]) == 1


@respx.mock
async def test_concurrent_runs_single_call(store):
    route = respx.post(OPENAI).mock(return_value=llm_reply())
    await asyncio.gather(postcall.run("m_01"), postcall.run("m_01"))
    assert route.call_count == 1


@respx.mock
async def test_llm_500_no_event_no_raise(store):
    respx.post(OPENAI).mock(return_value=httpx.Response(500))
    await postcall.run("m_01")
    assert store["events"] == []
    assert store["m"]["summary"] == ""


def test_merge_dedupes():
    out = postcall.merge_action_items(
        [{"owner": "A", "text": "Do X", "due": None}],
        [{"owner": "B", "text": " do  x ", "due": "Mon"}, {"owner": "B", "text": "Y", "due": None}],
    )
    assert [i["text"] for i in out] == ["Do X", "Y"]


def test_leave_schedules_run(monkeypatch):
    calls = []

    async def fake_run(mid):
        calls.append(mid)

    async def get_meeting(mid):
        return {"id": mid, "recall_bot_id": None, "status": "done"}

    monkeypatch.setattr(db, "get_meeting", get_meeting)
    monkeypatch.setattr(postcall, "run", fake_run)
    monkeypatch.setattr(postcall, "LEAVE_DELAY_S", 0)
    with TestClient(app) as client:
        r = client.post("/meetings/m_01/leave", headers={"Authorization": "Bearer demo-t"})
        assert r.status_code == 200
        import time

        end = time.monotonic() + 2
        while not calls and time.monotonic() < end:
            time.sleep(0.01)
    assert calls == ["m_01"]


def test_prompt_includes_agent_lines_in_order(monkeypatch):
    """The summary sees what the agent said (e.g. the INC-011 finding), not only humans."""
    monkeypatch.setenv("AGENT_NAME", "Atlas")
    get_settings.cache_clear()
    prompt = postcall.build_prompt(
        "brief",
        [{"speaker": "Marek", "text": "Atlas, similar outage before?", "ts_start": 18}],
        [],
        [{"text": "Yes. INC-011 matched both symptoms.", "ts": 23}],
    )
    assert prompt.index("Marek: Atlas, similar") < prompt.index("Atlas (AI): Yes. INC-011")
    get_settings.cache_clear()

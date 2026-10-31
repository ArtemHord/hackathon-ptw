import json
from pathlib import Path

import httpx
import pytest
import respx

from app import db, factcheck, hub, rag, recall
from app.config import get_settings

MOCKS = Path(__file__).resolve().parents[2] / "mocks"
OPENAI = "https://api.openai.com/v1/chat/completions"
LINE = {"id": "u1", "speaker": "Bob", "text": "Our API limit is 100 requests per second", "ts": 312}


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("OPENAI_CHAT_MODEL", "m")
    get_settings.cache_clear()
    factcheck._last_post.clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def fx(env, monkeypatch):
    class S:
        chats: list = []
        stored: list = []
        events: list = []

    s = S()
    s.chats, s.stored, s.events = [], [], []

    async def search(*a, **k):
        return [{"kind": "kb", "text": "Rate limit: 50 rps", "score": 0.9, "doc_title": "api.md"}]

    async def get_meeting(mid):
        return {"id": mid, "recall_bot_id": "bot1"}

    async def send(bot_id, text):
        s.chats.append((bot_id, text))
        return True

    async def insert(mid, **kw):
        s.stored.append(kw)
        return {"id": "fc_01"}

    async def publish(mid, type_, data):
        s.events.append((mid, type_, data))
        return 1

    async def chunk(title):
        return "kc_1" if title == "api.md" else None

    monkeypatch.setattr(db, "kb_chunk_for_title", chunk)
    monkeypatch.setattr(rag, "search", search)
    monkeypatch.setattr(db, "get_meeting", get_meeting)
    monkeypatch.setattr(recall, "send_chat_message", send)
    monkeypatch.setattr(db, "insert_fact_check", insert)
    monkeypatch.setattr(hub, "publish", publish)
    return s


def llm_reply(verdict="contradicted", confidence=0.95):
    content = {
        "claim": "limit is 100 rps",
        "verdict": verdict,
        "confidence": confidence,
        "source_title": "api.md",
        "correction": "50 rps",
        "chat_message": "Heads-up: api.md says the rate limit is 50 rps, not 100 (updated 12 Oct)",
    }
    return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(content)}}]})


async def test_filter_skips_without_llm(fx):
    with respx.mock(assert_all_called=False) as m:
        route = m.post(OPENAI).mock(return_value=llm_reply())
        await factcheck.check("m_01", {**LINE, "text": "hello everyone"})
        assert not route.called
    assert fx.stored == [] and fx.chats == []


async def test_contradiction_posts_and_matches_mock(fx):
    with respx.mock() as m:
        m.post(OPENAI).mock(return_value=llm_reply())
        await factcheck.check("m_01", LINE)
    assert fx.chats[0][0] == "bot1" and fx.chats[0][1].startswith("Heads-up: api.md says")
    assert fx.stored[0]["kb_chunk_id"] == "kc_1"
    assert fx.stored[0]["posted"] is True and fx.stored[0]["verdict"] == "contradicted"
    mid, type_, data = fx.events[0]
    mock = json.loads((MOCKS / "ws_fact_check.json").read_text())
    assert type_ == "fact_check" and set(data) == set(mock["data"])
    assert data["verdict"] == "contradicted" and data["source"] == "api.md"
    assert data["correction"] == "50 rps" and data["ts"] == 312


async def test_second_within_60s_stored_not_posted(fx):
    with respx.mock() as m:
        m.post(OPENAI).mock(return_value=llm_reply())
        await factcheck.check("m_01", LINE)
        await factcheck.check("m_01", LINE)
    assert len(fx.chats) == 1
    assert [r["posted"] for r in fx.stored] == [True, False]


async def test_low_confidence_not_posted(fx):
    with respx.mock() as m:
        m.post(OPENAI).mock(return_value=llm_reply(confidence=0.7))
        await factcheck.check("m_01", LINE)
    assert fx.chats == [] and fx.stored[0]["posted"] is False and len(fx.events) == 1


async def test_change_maps_to_unverified(fx):
    with respx.mock() as m:
        m.post(OPENAI).mock(return_value=llm_reply(verdict="change"))
        await factcheck.check("m_01", LINE)
    assert fx.chats == [] and fx.events[0][2]["verdict"] == "unverified"


async def test_crew_trigger_skipped(fx):
    with respx.mock(assert_all_called=False) as m:
        route = m.post(OPENAI).mock(return_value=llm_reply())
        await factcheck.check("m_01", {**LINE, "text": "Crew, what is our API limit of 50?"})
        assert not route.called
    assert fx.stored == []


async def test_llm_error_never_raises(fx):
    with respx.mock() as m:
        m.post(OPENAI).mock(return_value=httpx.Response(500, text="boom"))
        await factcheck.check("m_01", LINE)
    assert fx.stored == [] and fx.events == []

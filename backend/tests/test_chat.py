import json
from datetime import UTC
from pathlib import Path

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from app import chat, db, rag
from app.config import get_settings
from app.main import app

MOCK = json.loads((Path(__file__).resolve().parents[2] / "mocks" / "chat.json").read_text())
AUTH = {"Authorization": "Bearer demo-t"}
CHAT = "https://api.openai.com/v1/chat/completions"
EMBED = "https://api.openai.com/v1/embeddings"

ITEMS = [
    {
        "kind": "utterances",
        "text": "Yes, 15 min TTL",
        "score": 0.9,
        "meeting_id": "m_01",
        "ts": 380.0,
        "speaker": "Dima",
    },
    {"kind": "kb", "text": "Limit is 50 rps", "score": 0.8, "doc_title": "api.md"},
    {
        "kind": "facts",
        "text": "Migration moves Friday",
        "score": 0.7,
        "meeting_id": "m_02",
        "ts": None,
        "speaker": "Dima",
    },
]


@pytest.fixture(autouse=True)
def env(monkeypatch):
    for k, v in {
        "WEBHOOK_TOKEN": "wh-t",
        "DEMO_TOKEN": "demo-t",
        "DATABASE_URL": "",
        "OPENAI_API_KEY": "sk",
        "OPENAI_CHAT_MODEL": "m",
        "OPENAI_EMBED_MODEL": "e",
    }.items():
        monkeypatch.setenv(k, v)
    get_settings.cache_clear()
    saved = []

    async def insert(role, text, citations):
        saved.append((role, text, citations))

    async def doc(title):
        return {"id": "kb_01", "title": title, "version": 2}

    async def utts(mid):
        return [{"speaker": "Dima", "text": "x", "ts_start": 42.0}]

    monkeypatch.setattr(db, "insert_chat_message", insert)
    monkeypatch.setattr(db, "kb_doc_by_title", doc)
    monkeypatch.setattr(db, "get_all_utterances", utts)
    monkeypatch.setattr(chat.rag, "search", _search(ITEMS))
    yield saved
    get_settings.cache_clear()


def _search(items):
    async def search(q, k=6, kinds=("kb", "facts", "utterances")):
        assert k == 8
        return items

    return search


def _llm(content):
    return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(content)}}]})


@respx.mock
def test_happy_path(env):
    out = {"answer": "TTL is 15 min.", "used": [1, 2, 3, 9, 1]}
    route = respx.post(CHAT).mock(return_value=_llm(out))
    r = TestClient(app).post("/chat", json={"question": "What did Dima say?"}, headers=AUTH)
    assert r.status_code == 200
    body = r.json()
    assert set(body) == set(MOCK)
    assert body["answer"] == "TTL is 15 min."
    assert len(body["citations"]) == 3  # 9 unknown, duplicate 1 ignored
    meeting, doc, fact = body["citations"]
    assert set(meeting) == set(MOCK["citations"][0])
    assert set(doc) == set(MOCK["citations"][2])
    assert meeting["ts"] == 380 and meeting["speaker"] == "Dima"
    assert doc["doc_id"] == "kb_01" and doc["version"] == 2
    assert fact["ts"] == 42  # fact without ts -> speaker's utterance ts
    sent = json.loads(route.calls[0].request.content)["messages"][1]["content"]
    assert "[1] Yes, 15 min TTL" in sent
    assert [m[0] for m in env] == ["user", "assistant"]


@respx.mock
def test_unknown_numbers_ignored():
    respx.post(CHAT).mock(return_value=_llm({"answer": "Hmm.", "used": [0, 7, -1]}))
    r = TestClient(app).post("/chat", json={"question": "q"}, headers=AUTH)
    assert r.json() == {"answer": "Hmm.", "citations": []}


@respx.mock
def test_no_sources_fallback(monkeypatch, env):
    monkeypatch.setattr(chat.rag, "search", _search([]))
    route = respx.post(CHAT)
    r = TestClient(app).post("/chat", json={"question": "q"}, headers=AUTH)
    assert r.json() == {"answer": chat.NOT_FOUND, "citations": []}
    assert not route.called
    assert env[-1][0] == "assistant"


@respx.mock
def test_llm_failure_fallback():
    respx.post(CHAT).mock(return_value=httpx.Response(500))
    r = TestClient(app).post("/chat", json={"question": "q"}, headers=AUTH)
    assert r.status_code == 200
    assert r.json() == {"answer": chat.NOT_FOUND, "citations": []}


@respx.mock
def test_search_embeds_via_respx(monkeypatch):
    monkeypatch.setattr(chat.rag, "search", rag.search)
    respx.post(EMBED).mock(
        return_value=httpx.Response(200, json={"data": [{"index": 0, "embedding": [0.1]}]})
    )

    async def vs(q, k, kinds):
        return []

    monkeypatch.setattr(db, "vector_search", vs)
    r = TestClient(app).post("/chat", json={"question": "q"}, headers=AUTH)
    assert r.json()["answer"] == chat.NOT_FOUND


def test_auth_and_validation():
    c = TestClient(app)
    assert c.post("/chat", json={"question": "q"}).status_code == 401
    assert c.post("/chat", json={"question": ""}, headers=AUTH).status_code == 422
    assert c.post("/chat", json={"question": "x" * 501}, headers=AUTH).status_code == 422


@respx.mock
def test_fact_ts_falls_back_to_answered_escalation(monkeypatch):
    async def no_utts(mid):
        return []

    async def answered(mid, name):
        assert (mid, name) == ("m_02", "Dima")
        return 355

    monkeypatch.setattr(db, "get_all_utterances", no_utts)
    monkeypatch.setattr(db, "answered_ts_for_expert", answered, raising=False)
    respx.post(CHAT).mock(return_value=_llm({"answer": "Thursday.", "used": [3]}))
    r = TestClient(app).post("/chat", json={"question": "q"}, headers=AUTH)
    assert r.json()["citations"][0]["ts"] == 355


def test_recent_calls_block_in_prompt(monkeypatch, env):
    from datetime import datetime

    async def lm(n):
        return [
            {
                "title": "Sync",
                "status": "ended",
                "started_at": datetime(2026, 10, 30, 12, 0, tzinfo=UTC),
                "ended_at": datetime(2026, 10, 30, 12, 30, tzinfo=UTC),
            }
        ]

    monkeypatch.setattr(db, "list_meetings", lm)
    block = __import__("asyncio").run(chat._recent_calls())
    assert "Sync | 2026-10-30 13:00 (Europe/Warsaw), 30 min | ended" in block

    async def boom(n):
        raise RuntimeError

    monkeypatch.setattr(db, "list_meetings", boom)
    assert __import__("asyncio").run(chat._recent_calls()) == ""

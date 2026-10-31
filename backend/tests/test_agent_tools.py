"""M8.1: Atlas tool calling (Responses API: web_search, search_knowledge, create_doc)."""

import asyncio
import json
import logging
from datetime import datetime

import httpx
import pytest
import respx

from app import agent_voice, db, escalation, hub, llm, orchestrator, rag, recall, runtime, speech
from app import tools as agent_tools
from app.config import get_settings

RESP_URL = "https://api.openai.com/v1/responses"
CHAT_URL = "https://api.openai.com/v1/chat/completions"
MID = "m_01"


@pytest.fixture(autouse=True)
def env(monkeypatch):
    for k, v in {
        "OPENAI_API_KEY": "sk-test",
        "OPENAI_CHAT_MODEL": "test-model",
        "DATABASE_URL": "",
        "AGENT_TOOLS": "true",
    }.items():
        monkeypatch.setenv(k, v)
    get_settings.cache_clear()
    runtime.reset()
    llm._client = None
    orchestrator._busy.clear()
    orchestrator._armed.clear()
    orchestrator._pending.clear()
    monkeypatch.setattr(orchestrator, "_experts_cache", None)
    monkeypatch.setattr(escalation, "_cache", None)
    yield
    runtime.reset()
    get_settings.cache_clear()
    llm._client = None


@pytest.fixture
def world(monkeypatch):
    w = {"said": [], "hook": [], "chat": [], "docs": [], "existing": set()}

    async def get_meeting_mode(meeting_id):
        return "delegate"

    async def get_brief(meeting_id):
        return "Artem finished the Slack escalation flow."

    async def get_recent_utterances(meeting_id, since_ts, limit=200):
        return [{"id": "u_1", "speaker": "Misha", "text": "Morning!", "ts_start": 12.0}]

    async def insert_agent_said(meeting_id, text, ts, in_reply_to=None):
        return {"id": "as_01", "text": text, "ts": ts, "in_reply_to": in_reply_to}

    async def say(meeting_id, text):
        w["said"].append(text)
        return True

    async def say_filler(meeting_id):
        w["said"].append("<filler>")
        return True

    async def publish(meeting_id, type_, data):
        return 1

    async def hook(meeting_id, question, topic, asked_by):
        w["hook"].append((question, topic))
        return {"expert": "Dima", "escalation_id": "esc_1"}

    async def get_meeting(meeting_id):
        return {"id": meeting_id, "recall_bot_id": "bot_1", "created_at": datetime(2026, 10, 30)}

    async def send_chat_message(bot_id, text):
        w["chat"].append((bot_id, text))
        return True

    async def list_kb_docs():
        return [{"id": f"d_{i}", "title": t, "version": 3} for i, t in enumerate(w["existing"])]

    async def upsert_doc(title, markdown):
        w["docs"].append((title, markdown))
        return {"id": "d_new", "title": title, "version": 1}

    w["facts"] = [
        {"kind": "facts", "text": "Dima owns billing.", "score": 0.8, "meeting_id": "m0"},
    ]
    w["kb"] = [{"kind": "kb", "text": "Rate limit is 50 rps.", "score": 0.9, "doc_title": "API"}]

    async def search(query, k=6, kinds=("kb", "facts", "utterances")):
        w.setdefault("searches", []).append((query, k, kinds))
        return [it for kind in kinds for it in w.get(kind, [])][:k]

    monkeypatch.setattr(db, "get_meeting_mode", get_meeting_mode)
    monkeypatch.setattr(db, "get_brief", get_brief)
    monkeypatch.setattr(db, "get_recent_utterances", get_recent_utterances)
    monkeypatch.setattr(db, "insert_agent_said", insert_agent_said)
    monkeypatch.setattr(db, "get_meeting", get_meeting)
    monkeypatch.setattr(db, "list_kb_docs", list_kb_docs)
    monkeypatch.setattr(rag, "upsert_doc", upsert_doc)
    monkeypatch.setattr(rag, "search", search)
    monkeypatch.setattr(recall, "send_chat_message", send_chat_message)
    monkeypatch.setattr(speech, "say", say)
    monkeypatch.setattr(speech, "say_filler", say_filler)
    monkeypatch.setattr(hub, "publish", publish)
    monkeypatch.setattr(orchestrator, "on_needs_expert", hook)
    monkeypatch.setattr(agent_voice, "is_speaking", lambda mid: False)
    return w


def response(rid, output):
    return httpx.Response(200, json={"id": rid, "object": "response", "output": output})


def final(
    rid="resp_2",
    answer="Python 3.15.2 is the latest stable release.",
    confidence=0.9,
    needs_expert=False,
    topic="",
    citations=(),
    searched=False,
    sources=(),
):
    content = json.dumps(
        {"answer": answer, "confidence": confidence, "needs_expert": needs_expert, "topic": topic}
    )
    annotations = [
        {"type": "url_citation", "url": u, "title": t, "start_index": 0, "end_index": 1}
        for u, t in citations
    ]
    output = [{"type": "reasoning", "id": "rs_1", "summary": []}]
    if searched:
        found = [{"type": "url", "url": u} for u in sources]
        action = {"type": "search", "query": "q", "sources": found}
        output.append(
            {"type": "web_search_call", "id": "ws_1", "status": "completed", "action": action}
        )
    output.append(
        {
            "type": "message",
            "id": "msg_1",
            "role": "assistant",
            "content": [{"type": "output_text", "text": content, "annotations": annotations}],
        }
    )
    return response(rid, output)


def fcall(name, args, rid="resp_1", call_id="call_1"):
    item = {
        "type": "function_call",
        "id": "fc_1",
        "call_id": call_id,
        "name": name,
        "arguments": json.dumps(args),
    }
    return response(rid, [item])


def chat_completion(answer="From the chat path.", needs_expert=False, topic=""):
    content = json.dumps(
        {"answer": answer, "confidence": 0.9, "needs_expert": needs_expert, "topic": topic}
    )
    return httpx.Response(
        200, json={"choices": [{"message": {"role": "assistant", "content": content}}]}
    )


def utt(text, speaker="Misha", ts=382):
    return {"id": "u_9", "speaker": speaker, "text": text, "ts": ts}


def bodies(route):
    return [json.loads(c.request.content) for c in route.calls]


async def drain():
    if orchestrator._bg:
        await asyncio.gather(*list(orchestrator._bg))


@respx.mock
async def test_direct_answer_one_request(world):
    route = respx.post(RESP_URL).mock(return_value=final(answer="Artem finished Slack."))
    chat = respx.post(CHAT_URL).mock(return_value=chat_completion())
    assert await orchestrator.ask(MID, utt("Atlas, what did Artem finish?"), "what did he finish?")

    assert world["said"] == ["Artem finished Slack."]
    assert chat.call_count == 0
    (body,) = bodies(route)
    assert body["model"] == "test-model"
    assert body["parallel_tool_calls"] is False
    assert body["reasoning"] == {"effort": "low"}
    assert [t["type"] for t in body["tools"]] == ["web_search", "function", "function"]
    assert body["include"] == ["web_search_call.action.sources"]
    assert body["tools"][0]["search_context_size"] == "low"
    assert {t.get("name") for t in body["tools"][1:]} == {"search_knowledge", "create_doc"}
    for t in body["tools"][1:]:
        assert t["strict"] and t["parameters"]["additionalProperties"] is False
    fmt = body["text"]["format"]
    assert fmt["type"] == "json_schema" and fmt["strict"] is True
    assert fmt["schema"] == orchestrator.ANSWER_SCHEMA
    assert "previous_response_id" not in body and "tool_choice" not in body
    system = body["input"][0]
    assert system["role"] == "system" and "## Tools" in system["content"]
    assert "NEVER search for anything internal" in system["content"]
    assert route.calls.last.request.headers["authorization"] == "Bearer sk-test"
    assert world["chat"] == []


@respx.mock
async def test_search_knowledge_round_then_final(world, caplog):
    caplog.set_level(logging.INFO, logger="app.orchestrator")
    route = respx.post(RESP_URL).mock(
        side_effect=[
            fcall("search_knowledge", {"query": "rate limit"}),
            final(answer="The rate limit is 50 requests per second."),
        ]
    )
    assert await orchestrator.ask(MID, utt("Atlas, our rate limit?"), "what is our rate limit?")

    assert world["said"] == ["The rate limit is 50 requests per second."]
    assert sorted(world["searches"]) == [("rate limit", 3, ("kb",)), ("rate limit", 6, ("facts",))]
    second = bodies(route)[1]
    assert second["previous_response_id"] == "resp_1"
    (item,) = second["input"]
    assert item["type"] == "function_call_output" and item["call_id"] == "call_1"
    out = json.loads(item["output"])
    assert out["results"][0] == {
        "title": "Past meeting fact",
        "text": "Someone (meeting 2026-10-30): Dima owns billing.",
    }
    assert out["results"][1] == {"title": "API", "text": "Rate limit is 50 rps."}
    assert "path=tools, tools=search_knowledge, rounds=1" in caplog.text


@respx.mock
async def test_web_search_citations_go_to_chat_not_speech(world, caplog):
    caplog.set_level(logging.INFO, logger="app.orchestrator")
    respx.post(RESP_URL).mock(
        return_value=final(
            answer=(
                "The latest stable Python is **3.15.2**. "
                "([python.org](https://www.python.org/downloads/?utm_source=openai))"
            ),
            searched=True,
            citations=[
                ("https://www.python.org/downloads/?utm_source=openai", "Python"),
                ("https://www.python.org/downloads/?utm_source=openai", "Python again"),
                ("https://docs.python.org/3/whatsnew/", "What's new"),
                ("https://example.com/third", "Third"),
            ],
        )
    )
    assert await orchestrator.ask(MID, utt("Atlas, latest Python?"), "latest stable Python?")
    await drain()

    assert world["said"] == ["The latest stable Python is 3.15.2."]
    assert world["chat"] == [
        (
            "bot_1",
            "Sources: https://www.python.org/downloads/ https://docs.python.org/3/whatsnew/",
        )
    ]
    assert "tools=web_search, rounds=0" in caplog.text


@respx.mock
async def test_web_search_sources_used_when_no_inline_citation(world):
    respx.post(RESP_URL).mock(
        return_value=final(
            answer="Python 3.15.2 is the latest stable release.",
            searched=True,
            sources=[
                "https://www.python.org/downloads/source/",
                "https://a.io/1",
                "https://b.io/2",
            ],
        )
    )
    assert await orchestrator.ask(MID, utt("Atlas, latest Python?"), "latest stable Python?")
    await drain()
    assert world["chat"] == [
        ("bot_1", "Sources: https://www.python.org/downloads/source/ https://a.io/1")
    ]


@respx.mock
async def test_create_doc_new_title(world):
    route = respx.post(RESP_URL).mock(
        side_effect=[
            fcall("create_doc", {"title": "Release checklist", "markdown": "# Steps\n- tag"}),
            final(answer="I created the doc Release checklist."),
        ]
    )
    assert await orchestrator.ask(MID, utt("Atlas, create a doc"), "create a release checklist doc")

    assert world["docs"] == [("Release checklist", "# Steps\n- tag")]
    assert world["said"] == ["I created the doc Release checklist."]
    out = json.loads(bodies(route)[1]["input"][0]["output"])
    assert out == {"created": True, "title": "Release checklist", "version": 1}


@respx.mock
async def test_create_doc_existing_title_refused(world):
    world["existing"].add("API")
    route = respx.post(RESP_URL).mock(
        side_effect=[
            fcall("create_doc", {"title": "API", "markdown": "overwrite"}),
            final(answer="A doc called API already exists, so I did not change it."),
        ]
    )
    assert await orchestrator.ask(MID, utt("Atlas, write the API doc"), "write the API doc")

    assert world["docs"] == []  # never modifies an existing doc
    out = json.loads(bodies(route)[1]["input"][0]["output"])
    assert "exists; edits go through KB proposals" in out["error"]


@respx.mock
async def test_timeout_falls_back_to_chat_json(world, monkeypatch, caplog):
    monkeypatch.setattr(orchestrator, "TOOLS_CAP_S", 0.05)
    monkeypatch.setattr(orchestrator, "FILLER_AFTER_S", 5.0)

    async def slow(*a, **k):
        await asyncio.sleep(5)

    monkeypatch.setattr(llm, "respond", slow)
    chat = respx.post(CHAT_URL).mock(return_value=chat_completion("Fallback answer."))
    assert await orchestrator.ask(MID, utt("Atlas, anything?"), "anything new?")

    assert world["said"] == ["Fallback answer."]
    assert chat.call_count == 1
    assert "## Tools" not in json.loads(chat.calls.last.request.content)["messages"][0]["content"]
    assert "falling back to chat_json" in caplog.text


@respx.mock
async def test_responses_error_falls_back_to_chat_json(world):
    respx.post(RESP_URL).mock(return_value=httpx.Response(400, json={"error": {"message": "x"}}))
    respx.post(CHAT_URL).mock(return_value=chat_completion("Fallback answer."))
    assert await orchestrator.ask(MID, utt("Atlas, anything?"), "anything new?")
    assert world["said"] == ["Fallback answer."]


@respx.mock
async def test_needs_expert_still_escalates(world):
    respx.post(RESP_URL).mock(
        return_value=final(
            answer="",
            confidence=0.1,
            needs_expert=True,
            topic="database",
            citations=[("https://www.postgresql.org/", "PostgreSQL")],
        )
    )
    q = "when do we migrate to Postgres 17?"
    assert await orchestrator.ask(MID, utt(f"Atlas, {q}"), q)
    await drain()

    assert world["hook"] == [(q, "database")]
    assert world["said"] == ["I don't know, asking Dima now."]
    assert world["chat"] == []  # no sources posted for an escalation


@respx.mock
async def test_rounds_capped_last_request_forbids_tools(world):
    route = respx.post(RESP_URL).mock(
        side_effect=[
            fcall("search_knowledge", {"query": "a"}, rid="r1", call_id="c1"),
            fcall("search_knowledge", {"query": "b"}, rid="r2", call_id="c2"),
            final(rid="r3", answer="Done."),
        ]
    )
    assert await orchestrator.ask(MID, utt("Atlas, dig in"), "dig into this")
    b = bodies(route)
    assert len(b) == 3
    assert "tool_choice" not in b[1]
    assert b[2]["tool_choice"] == "none" and b[2]["previous_response_id"] == "r2"
    assert world["said"] == ["Done."]


@respx.mock
async def test_agent_tools_off_uses_chat_json_only(world):
    await runtime.save({"AGENT_TOOLS": "false"})
    resp = respx.post(RESP_URL).mock(return_value=final())
    respx.post(CHAT_URL).mock(return_value=chat_completion("Chat path."))
    assert await orchestrator.ask(MID, utt("Atlas, hi there"), "hi there friend")
    assert resp.call_count == 0
    assert world["said"] == ["Chat path."]


def test_spoken_strips_links_and_markdown():
    assert orchestrator.spoken("See [the docs](https://x.io/a) now.") == "See the docs now."
    assert orchestrator.spoken("It is **3.15** (https://python.org).") == "It is 3.15."
    assert orchestrator.spoken("Plain answer.") == "Plain answer."


async def test_execute_bad_input_returns_error():
    assert "unknown tool" in await agent_tools.execute("rm_rf", "{}")
    bad = json.loads(await agent_tools.execute("search_knowledge", "not json"))
    assert "failed" in bad["error"]
    out = json.loads(await agent_tools.execute("create_doc", json.dumps({"title": "x"})))
    assert "error" in out


async def test_create_doc_title_match_is_case_insensitive(world):
    world["existing"].add("Release Checklist")
    out = await agent_tools.create_doc("  release checklist ", "# overwrite")
    assert "'Release Checklist' exists" in out["error"]
    assert world["docs"] == []


async def test_concurrent_create_doc_same_title_writes_once(world, monkeypatch):
    async def slow_upsert(title, markdown):
        await asyncio.sleep(0.05)  # the embedding call between check and write
        world["docs"].append((title, markdown))
        world["existing"].add(title)
        return {"id": "d_new", "title": title, "version": 1}

    monkeypatch.setattr(rag, "upsert_doc", slow_upsert)
    a, b = await asyncio.gather(
        agent_tools.create_doc("Plan", "one"), agent_tools.create_doc("plan", "two")
    )
    assert world["docs"] == [("Plan", "one")]
    assert a["created"] is True and "exists" in b["error"]


@respx.mock
async def test_tool_timeout_plus_slow_fallback_is_bounded(world, monkeypatch):
    monkeypatch.setattr(orchestrator, "TOOLS_CAP_S", 0.1)
    monkeypatch.setattr(orchestrator, "ANSWER_BUDGET_S", 0.3)
    monkeypatch.setattr(orchestrator, "FALLBACK_MIN_S", 0.05)
    monkeypatch.setattr(orchestrator, "FILLER_AFTER_S", 5.0)

    async def slow(*a, **k):
        await asyncio.sleep(5)

    monkeypatch.setattr(llm, "respond", slow)
    monkeypatch.setattr(llm, "chat_json", slow)
    loop = asyncio.get_running_loop()
    t0 = loop.time()
    assert await orchestrator.ask(MID, utt("Atlas, anything?"), "anything new?") is False
    assert loop.time() - t0 < 1.0  # tool cap + fallback bounded by the budget, not 5 s + 5 s
    assert world["said"] == []  # silent failure, as before


async def test_search_knowledge_expert_answer_not_crowded_out_by_kb(world):
    """M8.1b: long KB chunks used to fill the top 4 and hide a short expert answer."""
    world["kb"] = [
        {"kind": "kb", "text": f"chunk {i}", "score": 0.9, "doc_title": f"doc{i}"} for i in range(6)
    ]
    answer = {
        "kind": "facts",
        "text": "Q: when do we migrate to Postgres 17?\nA: Thursday",
        "score": 0.15,
        "meeting_id": "m_9",
        "speaker": "Dima",
    }
    brief = {"kind": "facts", "text": "Artem cannot promise dates.", "speaker": "Brief"}
    world["facts"] = [answer, dict(answer, meeting_id="m_8"), brief, brief, brief]
    out = await agent_tools.search_knowledge("what did Dima say about the migration?")
    texts = [r["text"] for r in out["results"]]
    assert texts == [
        'Dima (meeting 2026-10-30), asked "when do we migrate to Postgres 17?", answered: Thursday',
        "Brief (meeting unknown date): Artem cannot promise dates.",
        "chunk 0",
        "chunk 1",
        "chunk 2",
    ]  # deduped facts first (top 3), then top 3 KB


async def test_search_knowledge_meeting_lookup_failure_still_returns(world, monkeypatch):
    async def boom(meeting_id):
        raise RuntimeError("db down")

    monkeypatch.setattr(db, "get_meeting", boom)
    out = await agent_tools.search_knowledge("billing")
    assert out["results"][0]["text"] == "Someone (meeting unknown date): Dima owns billing."


def test_tools_prompt_lets_agent_quote_an_earlier_expert_answer():
    assert "earlier answer" in orchestrator.TOOLS_PROMPT
    assert "not a commitment" in orchestrator.TOOLS_PROMPT


async def test_vector_search_single_kind_names_columns(monkeypatch):
    """A facts-only search used to fail: only the kb branch of the UNION named its columns."""
    seen = {}

    class Pool:
        async def fetch(self, sql, *args):
            seen["sql"] = sql
            return []

    async def get_pool():
        return Pool()

    monkeypatch.setattr(db, "get_pool", get_pool)
    for kind in ("facts", "utterances"):
        await db.vector_search([0.1], 3, (kind,))
        assert f"'{kind}' as kind" in seen["sql"] and "as score" in seen["sql"]

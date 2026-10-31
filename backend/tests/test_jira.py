"""M7.4 Jira: client (ADF, keys, get/create), in-call lookup, post-call auto-create,
manual action-item endpoint, escalation-timeout follow-up. All HTTP mocked with respx."""

import asyncio
import json

import httpx
import pytest
import respx

from app import (
    agent_voice,
    db,
    escalation,
    hub,
    jira,
    llm,
    orchestrator,
    postcall,
    runtime,
    speech,
)
from app.config import get_settings
from app.main import app
from app.notifier import base as notifier_base

JIRA = "https://acme.atlassian.net"
OPENAI = "https://api.openai.com/v1/chat/completions"
AUTH = {"Authorization": "Bearer demo-t"}
ISSUE = f"{JIRA}/rest/api/3/issue"


@pytest.fixture(autouse=True)
def env(monkeypatch):
    for k, v in {
        "OPENAI_API_KEY": "sk-test",
        "OPENAI_CHAT_MODEL": "test-model",
        "DEMO_TOKEN": "demo-t",
        "DATABASE_URL": "",
        "AGENT_NAME": "Atlas",
        "OWNER_NAME": "Artem",
        "JIRA_BASE_URL": "",
        "JIRA_EMAIL": "",
        "JIRA_API_TOKEN": "",
        "JIRA_PROJECT_KEY": "",
        "JIRA_AUTO_CREATE": "",
    }.items():
        monkeypatch.setenv(k, v)
    get_settings.cache_clear()
    runtime.reset()
    llm._client = None
    jira._locks.clear()
    orchestrator._busy.clear()
    monkeypatch.setattr(orchestrator, "_experts_cache", "- Dima: infra")
    yield
    runtime.reset()
    get_settings.cache_clear()
    llm._client = None


@pytest.fixture
def jira_on():
    runtime._overrides.update(
        {
            "JIRA_BASE_URL": JIRA + "/",
            "JIRA_EMAIL": "bot@acme.io",
            "JIRA_API_TOKEN": "jt",
            "JIRA_PROJECT_KEY": "ptw",
        }
    )
    return True


def issue_json(key="PTW-12", assignee="Dima K", due="2026-11-05"):
    return {
        "id": "10012",
        "key": key,
        "fields": {
            "summary": "Rate limit rollout",
            "status": {"name": "In Progress"},
            "assignee": {"displayName": assignee} if assignee else None,
            "duedate": due,
            "description": {
                "type": "doc",
                "version": 1,
                "content": [
                    {"type": "paragraph", "content": [{"type": "text", "text": "Raise to 100."}]}
                ],
            },
        },
    }


# --- pure helpers ---------------------------------------------------------------


def text_node(t):
    return {"type": "text", "text": t}


def para(t):
    return {"type": "paragraph", "content": [text_node(t)]}


def test_adf_text():
    doc = {
        "type": "doc",
        "version": 1,
        "content": [
            {"type": "heading", "attrs": {"level": 2}, "content": [text_node("Plan")]},
            {
                "type": "paragraph",
                "content": [
                    {"type": "text", "text": "Ping "},
                    {"type": "mention", "attrs": {"id": "x", "text": "@Dima"}},
                    {"type": "hardBreak"},
                    {"type": "emoji", "attrs": {"shortName": ":ok:", "text": "👍"}},
                ],
            },
            {
                "type": "bulletList",
                "content": [
                    {
                        "type": "listItem",
                        "content": [para("a")],
                    }
                ],
            },
        ],
    }
    assert jira.adf_text(doc) == "Plan\nPing @Dima\n👍\na"
    assert jira.adf_text(None) == ""
    assert jira.adf_text("plain") == "plain"
    long = {"type": "doc", "content": [para("x" * 900)]}
    assert len(jira.adf_text(long)) == jira.DESCRIPTION_MAX


@pytest.mark.parametrize(
    "text,project,keys",
    [
        ("what's the status of PTW-12?", None, ["PTW-12"]),
        ("status of ptw 12", "PTW", ["PTW-12"]),
        ("status of ptw12 and PTW-3", "PTW", ["PTW-12", "PTW-3"]),
        ("what about ticket 12?", "PTW", ["PTW-12"]),
        ("issue number 7 please", "ptw", ["PTW-7"]),
        ("what about ticket 12?", None, []),
        ("status of ptw 12", None, []),  # lowercase, no project: not a key
        ("when do we migrate to Postgres 17 with limit 100?", "PTW", []),
        ("what did Artem finish?", "PTW", []),
        ("PTW-12 and PTW 12 again", "PTW", ["PTW-12"]),
    ],
)
def test_extract_keys(text, project, keys):
    assert jira.extract_keys(text, project) == keys


# --- client ----------------------------------------------------------------------


@respx.mock
async def test_get_issue_200_and_404(jira_on):
    ok = respx.get(f"{ISSUE}/PTW-12").mock(return_value=httpx.Response(200, json=issue_json()))
    respx.get(f"{ISSUE}/PTW-99").mock(
        return_value=httpx.Response(404, json={"errorMessages": ["Issue does not exist"]})
    )
    got = await jira.get_issue("PTW-12")
    assert got == {
        "key": "PTW-12",
        "summary": "Rate limit rollout",
        "status": "In Progress",
        "assignee": "Dima K",
        "due": "2026-11-05",
        "description": "Raise to 100.",
        "url": f"{JIRA}/browse/PTW-12",
    }
    assert "summary" in ok.calls.last.request.url.params["fields"]
    assert await jira.get_issue("PTW-99") is None


@respx.mock
async def test_get_issue_unassigned_no_description(jira_on):
    body = issue_json(assignee=None, due=None)
    body["fields"]["description"] = None
    respx.get(f"{ISSUE}/PTW-1").mock(return_value=httpx.Response(200, json=body))
    got = await jira.get_issue("PTW-1")
    assert got["assignee"] is None and got["due"] is None and got["description"] == ""


@respx.mock
async def test_create_issue_adf_due_assignee(jira_on):
    search = respx.get(f"{JIRA}/rest/api/3/user/search").mock(
        return_value=httpx.Response(
            200, json=[{"accountId": "acc-1", "displayName": "Dima", "emailAddress": "d@acme.io"}]
        )
    )
    create = respx.post(ISSUE).mock(
        return_value=httpx.Response(201, json={"id": "1", "key": "PTW-42", "self": "x"})
    )
    out = await jira.create_issue("Update docs", "Line 1\nLine 2", "2026-11-03", "d@acme.io")
    assert out == {"key": "PTW-42", "url": f"{JIRA}/browse/PTW-42"}
    assert search.calls.last.request.url.params["query"] == "d@acme.io"
    fields = json.loads(create.calls.last.request.content)["fields"]
    assert fields["project"] == {"key": "PTW"}
    assert fields["issuetype"] == {"name": "Task"}
    assert fields["duedate"] == "2026-11-03"
    assert fields["assignee"] == {"accountId": "acc-1"}
    assert fields["description"]["type"] == "doc" and fields["description"]["version"] == 1
    texts = [p["content"][0]["text"] for p in fields["description"]["content"]]
    assert texts == ["Line 1", "Line 2"]


@respx.mock
async def test_create_issue_non_iso_due_and_unknown_assignee(jira_on):
    respx.get(f"{JIRA}/rest/api/3/user/search").mock(return_value=httpx.Response(200, json=[]))
    create = respx.post(ISSUE).mock(return_value=httpx.Response(201, json={"key": "PTW-1"}))
    await jira.create_issue("x" * 300, "d", "Friday", "nobody@acme.io")
    fields = json.loads(create.calls.last.request.content)["fields"]
    assert "duedate" not in fields and "assignee" not in fields
    assert len(fields["summary"]) == jira.SUMMARY_MAX


@respx.mock
async def test_create_issue_issuetype_fallback(jira_on):
    create = respx.post(ISSUE).mock(
        side_effect=[
            httpx.Response(400, json={"errors": {"issuetype": "Specify a valid issue type"}}),
            httpx.Response(201, json={"key": "PTW-7"}),
        ]
    )
    respx.get(f"{ISSUE}/createmeta/PTW/issuetypes").mock(
        return_value=httpx.Response(
            200,
            json={
                "issueTypes": [
                    {"id": "10003", "name": "Sub-task", "subtask": True},
                    {"id": "10001", "name": "Story", "subtask": False},
                ]
            },
        )
    )
    out = await jira.create_issue("Do it", "desc")
    assert out["key"] == "PTW-7"
    second = json.loads(create.calls[1].request.content)["fields"]
    assert second["issuetype"] == {"id": "10001"}


@respx.mock
async def test_create_issue_error_message(jira_on):
    respx.post(ISSUE).mock(
        return_value=httpx.Response(
            400, json={"errorMessages": ["Bad thing"], "errors": {"summary": "required"}}
        )
    )
    with pytest.raises(jira.JiraError) as e:
        await jira.create_issue("x", "y")
    assert e.value.status == 400
    assert "Bad thing" in str(e.value) and "summary: required" in str(e.value)


async def test_create_issue_needs_project(monkeypatch, jira_on):
    runtime._overrides.pop("JIRA_PROJECT_KEY")
    with pytest.raises(jira.JiraError):
        await jira.create_issue("x", "y")


# --- in-call lookup ----------------------------------------------------------------


def completion(answer="PTW-12 is in progress, Dima has it, due November 5th."):
    content = json.dumps({"answer": answer, "confidence": 0.9, "needs_expert": False, "topic": ""})
    return httpx.Response(
        200,
        json={
            "id": "c1",
            "object": "chat.completion",
            "created": 1,
            "model": "test-model",
            "choices": [
                {
                    "index": 0,
                    "finish_reason": "stop",
                    "message": {"role": "assistant", "content": content, "refusal": None},
                }
            ],
        },
    )


@pytest.fixture
def call(monkeypatch):
    w = {"said": [], "events": []}

    async def mode(mid):
        return "delegate"

    async def brief(mid):
        return "Artem works on the API."

    async def recent(mid, since, limit=200):
        return []

    async def agent_said(mid, text, ts, in_reply_to=None):
        return {"id": "as_1"}

    async def say(mid, text):
        w["said"].append(text)
        return True

    async def filler(mid):
        w["said"].append("<filler>")
        return True

    async def publish(mid, type_, data):
        w["events"].append((type_, data))
        return 1

    async def nothing(*a, **k):
        return None

    monkeypatch.setattr(db, "get_meeting_mode", mode)
    monkeypatch.setattr(db, "get_brief", brief)
    monkeypatch.setattr(db, "get_recent_utterances", recent)
    monkeypatch.setattr(db, "insert_agent_said", agent_said)
    monkeypatch.setattr(speech, "say", say)
    monkeypatch.setattr(speech, "say_filler", filler)
    monkeypatch.setattr(hub, "publish", publish)
    monkeypatch.setattr(agent_voice, "is_speaking", lambda mid: False)
    monkeypatch.setattr(agent_voice, "send_state", nothing)
    return w


UTT = {"id": "u_1", "speaker": "Misha", "text": "Atlas, status of PTW-12?", "ts": 100}


@respx.mock
async def test_answer_with_jira_section(call, jira_on):
    issue = respx.get(f"{ISSUE}/PTW-12").mock(return_value=httpx.Response(200, json=issue_json()))
    missing = respx.get(f"{ISSUE}/PTW-404").mock(return_value=httpx.Response(404, json={}))
    llm_route = respx.post(OPENAI).mock(return_value=completion())
    ok = await orchestrator.ask("m_1", UTT, "what's the status of PTW-12 and PTW-404?")
    assert ok is True
    assert issue.called and missing.called
    body = json.loads(llm_route.calls.last.request.content)
    system, user = body["messages"][0]["content"], body["messages"][1]["content"]
    assert "## Jira" in system  # the rule about the section
    assert "## Jira" in user
    assert "PTW-12: Rate limit rollout" in user and "Status: In Progress" in user
    assert "Assignee: Dima K" in user and "Due: 2026-11-05" in user
    assert "PTW-404: not found in Jira." in user
    assert call["said"][-1].startswith("PTW-12 is in progress")


@respx.mock
async def test_jira_lookup_failure_proceeds(call, jira_on):
    respx.get(f"{ISSUE}/PTW-12").mock(return_value=httpx.Response(500))
    llm_route = respx.post(OPENAI).mock(return_value=completion("I'm not sure."))
    assert await orchestrator.ask("m_1", UTT, "status of PTW-12?") is True
    user = json.loads(llm_route.calls.last.request.content)["messages"][1]["content"]
    assert "## Jira" not in user


@respx.mock
async def test_jira_lookup_timeout_proceeds(call, jira_on, monkeypatch):
    monkeypatch.setattr(orchestrator, "JIRA_LOOKUP_S", 0.05)
    monkeypatch.setattr(orchestrator, "FILLER_AFTER_S", 0.01)

    async def slow(request):
        await asyncio.sleep(1)
        return httpx.Response(200, json=issue_json())

    respx.get(f"{ISSUE}/PTW-12").mock(side_effect=slow)
    llm_route = respx.post(OPENAI).mock(return_value=completion("ok"))
    assert await orchestrator.ask("m_1", UTT, "status of PTW-12?") is True
    user = json.loads(llm_route.calls.last.request.content)["messages"][1]["content"]
    assert "## Jira" not in user
    assert call["said"] == ["<filler>", "ok"]  # filler covered the slow lookup, played once


async def test_jira_unconfigured_no_calls(call):
    with respx.mock(assert_all_called=False) as rm:
        jira_route = rm.route(host="acme.atlassian.net")
        llm_route = rm.post(OPENAI).mock(return_value=completion("fine"))
        assert await orchestrator.ask("m_1", UTT, "status of PTW-12?") is True
    assert not jira_route.called
    user = json.loads(llm_route.calls.last.request.content)["messages"][1]["content"]
    assert "## Jira" not in user


def test_build_messages_positional_compat():
    msgs = orchestrator.build_messages("b", [], "Misha", "q?", "- Dima: infra")
    assert "## Jira" not in msgs[1]["content"]
    assert "- Dima: infra" in msgs[0]["content"]


# --- action items: fake meeting store -------------------------------------------------


@pytest.fixture
def store(monkeypatch):
    m = {
        "id": "m_01",
        "title": "Q4 API sync",
        "summary": "",
        "decisions": [],
        "status": "done",
        "action_items": [
            {"owner": "Dima", "text": "Confirm the rollout date", "due": None},
            {"owner": "Anna", "text": "Update the docs", "due": "2026-11-03"},
        ],
    }

    async def get_meeting(mid):
        return json.loads(json.dumps(m)) if mid == "m_01" else None

    async def update_meeting(mid, **kw):
        m.update(json.loads(json.dumps(kw)))
        return dict(m)

    async def set_jira(mid, item_id, key, url):
        """Same semantics as db.set_action_item_jira (ids persisted, existing key kept)."""
        items = db.with_item_ids(m["action_items"])
        hit = next((a for a in items if a["id"] == item_id), None)
        if hit is None:
            return None
        if not hit.get("jira_key"):
            hit.update(jira_key=key, jira_url=url)
        m["action_items"] = items
        return dict(hit)

    monkeypatch.setattr(db, "get_meeting", get_meeting)
    monkeypatch.setattr(db, "update_meeting", update_meeting)
    monkeypatch.setattr(db, "set_action_item_jira", set_jira)
    dima = notifier_base.Expert(name="Dima", email="d@acme.io")
    monkeypatch.setattr(escalation, "_cache", [dima])
    return m


def numbered_creates():
    n = {"i": 0}

    def make(request):
        n["i"] += 1
        return httpx.Response(201, json={"key": f"PTW-{n['i']}"})

    return make


@respx.mock
async def test_auto_create_idempotent(store, jira_on):
    respx.get(f"{JIRA}/rest/api/3/user/search").mock(
        return_value=httpx.Response(200, json=[{"accountId": "acc-d", "emailAddress": "d@acme.io"}])
    )
    create = respx.post(ISSUE).mock(side_effect=numbered_creates())
    assert await jira.auto_create("m_01") == 2
    assert await jira.auto_create("m_01") == 0
    await asyncio.gather(jira.auto_create("m_01"), jira.auto_create("m_01"))
    assert create.call_count == 2
    items = store["action_items"]
    assert [(i["id"], i["jira_key"]) for i in items] == [("ai_01", "PTW-1"), ("ai_02", "PTW-2")]
    assert items[0]["jira_url"] == f"{JIRA}/browse/PTW-1"
    first = json.loads(create.calls[0].request.content)["fields"]
    assert first["summary"] == "Confirm the rollout date"
    assert first["assignee"] == {"accountId": "acc-d"}
    desc = first["description"]["content"][0]["content"][0]["text"]
    assert desc == "From meeting Q4 API sync (Call Crew). Owner: Dima. Due: not set."
    second = json.loads(create.calls[1].request.content)["fields"]
    assert second["duedate"] == "2026-11-03" and "assignee" not in second


async def test_auto_create_never_raises(store, jira_on, monkeypatch):
    async def boom(mid):
        raise RuntimeError("db down")

    monkeypatch.setattr(db, "get_meeting", boom)
    assert await jira.auto_create("m_01") == 0


def postcall_reply():
    out = {
        "summary": "Limit raised.",
        "decisions": [],
        "action_items": [{"owner": "Anna", "text": "Write the changelog", "due": None}],
        "facts": [],
    }
    return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(out)}}]})


@pytest.fixture
def postcall_world(store, monkeypatch):
    async def empty(mid):
        return []

    async def brief(mid):
        return ""

    async def publish(mid, type_, data):
        return 0

    store["action_items"] = [
        {"id": "ai_01", "owner": "Dima", "text": "Old", "due": None, "jira_key": "PTW-9",
         "jira_url": f"{JIRA}/browse/PTW-9"}
    ]  # fmt: skip
    monkeypatch.setattr(db, "get_all_utterances", empty)
    monkeypatch.setattr(db, "list_escalations", empty)
    monkeypatch.setattr(db, "get_brief", brief)
    monkeypatch.setattr(hub, "publish", publish)
    monkeypatch.setattr(postcall, "_locks", {})
    return store


async def drain():
    for _ in range(3):
        await asyncio.gather(*list(jira._tasks))
        await asyncio.sleep(0)


@respx.mock
async def test_postcall_auto_create_flag(postcall_world, jira_on):
    runtime._overrides["JIRA_AUTO_CREATE"] = "true"
    respx.post(OPENAI).mock(return_value=postcall_reply())
    respx.get(f"{JIRA}/rest/api/3/user/search").mock(return_value=httpx.Response(200, json=[]))
    create = respx.post(ISSUE).mock(return_value=httpx.Response(201, json={"key": "PTW-10"}))
    await postcall.run("m_01")
    await drain()
    assert create.call_count == 1  # the old item keeps PTW-9
    items = postcall_world["action_items"]
    got = [(i["id"], i.get("jira_key")) for i in items]
    assert got == [("ai_01", "PTW-9"), ("ai_02", "PTW-10")]


async def test_postcall_without_flag_creates_nothing(postcall_world, jira_on):
    with respx.mock(assert_all_called=False) as rm:
        rm.post(OPENAI).mock(return_value=postcall_reply())
        create = rm.post(ISSUE).mock(return_value=httpx.Response(201, json={"key": "X-1"}))
        await postcall.run("m_01")
        await drain()
    assert not create.called
    items = postcall_world["action_items"]
    assert items[0]["jira_key"] == "PTW-9" and items[1]["id"] == "ai_02"


def test_merge_keeps_ids_and_jira():
    out = postcall.merge_action_items(
        [
            {"owner": "A", "text": "One", "due": None},
            {
                "id": "ai_x",
                "owner": "B",
                "text": "Two",
                "due": None,
                "jira_key": "P-1",
                "jira_url": "u",
            },
        ],  # fmt: skip
        [{"owner": "C", "text": "two", "due": None}, {"owner": "C", "text": "Three", "due": None}],
    )
    assert [(i["id"], i["text"], i.get("jira_key")) for i in out] == [
        ("ai_01", "One", None),
        ("ai_x", "Two", "P-1"),
        ("ai_03", "Three", None),
    ]


# --- manual endpoint -------------------------------------------------------------------


def client():
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")


async def test_endpoint_auth_and_not_configured(store):
    async with client() as c:
        r401 = await c.post("/meetings/m_01/action-items/ai_01/jira")
        r404 = await c.post("/meetings/nope/action-items/ai_01/jira", headers=AUTH)
        r409 = await c.post("/meetings/m_01/action-items/ai_01/jira", headers=AUTH)
    assert r401.status_code == 401
    assert r404.status_code == 404
    assert r409.status_code == 409 and r409.json()["error"]["code"] == "not_configured"


@respx.mock
async def test_endpoint_create_then_idempotent(store, jira_on):
    respx.get(f"{JIRA}/rest/api/3/user/search").mock(return_value=httpx.Response(200, json=[]))
    create = respx.post(ISSUE).mock(return_value=httpx.Response(201, json={"key": "PTW-42"}))
    async with client() as c:
        first = await c.post("/meetings/m_01/action-items/ai_02/jira", headers=AUTH)
        again = await c.post("/meetings/m_01/action-items/ai_02/jira", headers=AUTH)
        missing = await c.post("/meetings/m_01/action-items/ai_77/jira", headers=AUTH)
    want = {"jira_key": "PTW-42", "url": f"{JIRA}/browse/PTW-42"}
    assert first.status_code == 200 and first.json() == want
    assert again.status_code == 200 and again.json() == want
    assert missing.status_code == 404
    assert create.call_count == 1
    assert store["action_items"][1]["jira_key"] == "PTW-42"
    assert "jira_key" not in store["action_items"][0]


@respx.mock
async def test_endpoint_upstream_error(store, jira_on):
    respx.get(f"{JIRA}/rest/api/3/user/search").mock(return_value=httpx.Response(200, json=[]))
    respx.post(ISSUE).mock(
        return_value=httpx.Response(400, json={"errors": {"project": "project is required"}})
    )
    async with client() as c:
        r = await c.post("/meetings/m_01/action-items/ai_01/jira", headers=AUTH)
    assert r.status_code == 502
    err = r.json()["error"]
    assert err["code"] == "upstream_error" and "project is required" in err["message"]


async def test_detail_exposes_jira_fields(store, monkeypatch):
    store["action_items"][0].update(jira_key="PTW-5", jira_url=f"{JIRA}/browse/PTW-5")

    async def detail(mid, since=None):
        return {
            "meeting": {**store, "mode": "delegate", "platform": "zoom"},
            "fact_checks": [],
            "escalations": [],
            "utterances": [],
            "agent_said": [],
        }

    monkeypatch.setattr(db, "get_meeting_detail", detail)
    async with client() as c:
        body = (await c.get("/meetings/m_01", headers=AUTH)).json()
    a, b = body["action_items"]
    assert (a["id"], a["jira_key"], a["jira_url"]) == ("ai_01", "PTW-5", f"{JIRA}/browse/PTW-5")
    assert (b["id"], b["jira_key"], b["jira_url"]) == ("ai_02", None, None)


# --- escalation timeout ---------------------------------------------------------------


@pytest.fixture
def timeout_world(store, monkeypatch):
    store["status"] = "in_call"
    store["action_items"] = []
    said = []

    async def timeout_escalation(eid):
        return {"id": eid, "expert": "Dima", "asked_by": "Misha", "ts": 10, "asked_at": None,
                "status": "timeout", "question": "When is the rollout?"}  # fmt: skip

    async def append(mid, item):
        store["action_items"].append(item)

    async def speak(*a, **k):
        said.append(a[1])

    async def nothing(*a, **k):
        return None

    monkeypatch.setattr(db, "timeout_escalation", timeout_escalation)
    monkeypatch.setattr(db, "append_action_item", append)
    monkeypatch.setattr(escalation, "_speak", speak)
    monkeypatch.setattr(escalation, "ESCALATION_TIMEOUT_S", 0)
    monkeypatch.setattr(agent_voice, "send_ask_done", nothing)
    monkeypatch.setattr(hub, "publish", nothing)
    store["said"] = said
    return store


@respx.mock
async def test_timeout_creates_followup_issue(timeout_world, jira_on):
    respx.get(f"{JIRA}/rest/api/3/user/search").mock(return_value=httpx.Response(200, json=[]))
    create = respx.post(ISSUE).mock(return_value=httpx.Response(201, json={"key": "PTW-77"}))
    await escalation._timeout("m_01", "esc_1", "Dima", "When is the rollout?")
    assert timeout_world["said"] == ["Dima hasn't answered yet — I've added it to follow-ups."]
    await drain()
    (item,) = timeout_world["action_items"]
    assert item["text"] == "When is the rollout?" and item["id"].startswith("ai_")
    assert item["jira_key"] == "PTW-77" and item["jira_url"] == f"{JIRA}/browse/PTW-77"
    fields = json.loads(create.calls.last.request.content)["fields"]
    assert fields["summary"] == "Follow-up: When is the rollout?"
    desc = fields["description"]["content"][0]["content"][0]["text"]
    assert desc == "Asked in Q4 API sync by Misha; Dima didn't answer within 2 min."
    # post-call auto-create then skips it
    assert await jira.auto_create("m_01") == 0


@respx.mock
async def test_timeout_jira_failure_is_logged(timeout_world, jira_on):
    respx.get(f"{JIRA}/rest/api/3/user/search").mock(return_value=httpx.Response(200, json=[]))
    respx.post(ISSUE).mock(return_value=httpx.Response(500))
    await escalation._timeout("m_01", "esc_1", "Dima", "When is the rollout?")
    await drain()
    (item,) = timeout_world["action_items"]
    assert "jira_key" not in item


async def test_timeout_without_jira_unchanged(timeout_world):
    await escalation._timeout("m_01", "esc_1", "Dima", "When is the rollout?")
    assert timeout_world["action_items"] == [
        {"owner": "Dima", "text": "When is the rollout?", "due": None}
    ]
    assert not jira._tasks

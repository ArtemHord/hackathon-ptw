"""M10: DEMO_PROFILE=msp: incident tools, guardrail prompt, citations to the chat, Jira skip,
named expert, experts per profile, default brief, simulate fixture. Small fixture files in
tmp_path (never the real seed/msp data); respx for OpenAI/Recall, no network."""

import json

import httpx
import pytest
import respx

from app import (
    agent_voice,
    db,
    escalation,
    factcheck,
    hub,
    jira,
    llm,
    orchestrator,
    profile,
    recall,
    runtime,
    simulate,
    speech,
)
from app import tools as agent_tools
from app.config import get_settings
from app.main import app
from app.notifier.base import Expert

RESP_URL = "https://api.openai.com/v1/responses"
RECALL = "https://eu-central-1.recall.ai"
DEMO = "demo-t"
AUTH = {"Authorization": f"Bearer {DEMO}"}
MID = "m_msp"

INCIDENTS = {
    "symptom_tags": {
        "payment_failure": "Payments fail",
        "wrong_prices": "Prices display incorrectly",
        "gateway_auth_401": "Gateway returns 401",
        "crm_sync_delay": "CRM sync delayed",
    },
    "incidents": [
        {
            "id": "INC-001",
            "date": "2026-07-01",
            "title": "Gateway key",
            "customer": "Shop",
            "symptoms": ["payment_failure", "gateway_auth_401"],
            "prices_correct": True,
            "root_cause": "Wrong gateway key.",
            "resolution": "Key updated.",
            "resolved_by": ["Marek"],
            "runbook": None,
            "quotes": [{"time": "09:14", "speaker": "Marek", "role": "Eng", "text": "HTTP 401."}],
            "lesson": "Not the same as a token problem.",
        },
        {
            "id": "INC-002",
            "date": "2026-06-01",
            "title": "Payments and prices",
            "customer": "Shop",
            "symptoms": ["payment_failure", "wrong_prices"],
            "prices_correct": False,
            "root_cause": "Expired CRM token.",
            "resolution": "Plugin isolated, token re-authorized.",
            "resolved_by": ["Ola"],
            "runbook": "RB-TEST-01",
            "quotes": [
                {"time": "14:08", "speaker": "Marek", "role": "Eng", "text": "auth_failure logs."},
                {"time": "14:12", "speaker": "Ola", "role": "SME", "text": "Staging test ok."},
                {"time": "14:19", "speaker": "Ola", "role": "S", "text": "Cause confirmed: token."},
                {"time": "14:21", "speaker": "Kamil", "role": "Lead", "text": "Checklist added."},
            ],
            "lesson": "Check integration logs.",
        },
        {
            "id": "INC-003",
            "date": "2026-08-01",
            "title": "Promo prices",
            "customer": "Shop",
            "symptoms": ["wrong_prices"],
            "prices_correct": False,
            "root_cause": "Discount rule.",
            "resolution": "Rule fixed.",
            "resolved_by": ["Patrycja"],
            "runbook": None,
            "quotes": [],
            "lesson": "Prices only.",
        },
        {
            "id": "INC-004",
            "date": "2026-09-01",
            "title": "CRM delay",
            "customer": "Shop",
            "symptoms": ["crm_sync_delay"],
            "prices_correct": True,
            "root_cause": "Queue.",
            "resolution": "Throughput up.",
            "resolved_by": ["Ola"],
            "runbook": None,
            "quotes": [],
            "lesson": "-",
        },
    ],
    "experts": [
        {
            "name": "Ola",
            "role": "Integrations SME",
            "areas": ["Salesforce", "CRM Bridge"],
            "resolved": ["INC-002"],
            "handle": "@ola",
            "approves": False,
        },
        {
            "name": "Marek",
            "role": "On-call engineer",
            "areas": ["payment gateway", "PHP"],
            "resolved": ["INC-001"],
            "handle": "@marek",
            "approves": False,
        },
        {
            "name": "Kamil",
            "role": "Incident Lead",
            "areas": ["mitigation approval"],
            "resolved": [],
            "handle": "@kamil",
            "approves": True,
        },
    ],
}
EXPERTS = {
    "experts": [
        {"name": "Ola", "role": "SME", "topics": ["salesforce", "crm bridge"], "channel": "slack",
         "email": "ola@example.com"},
        {"name": "Marek", "role": "Eng", "topics": ["payment gateway"], "channel": "slack",
         "email": None},
        {"name": "Kamil", "role": "Lead", "topics": ["owner", "incident lead"], "channel": "slack",
         "email": "kamil@example.com", "is_owner": True},
    ]
}  # fmt: skip
RUNBOOK = """# RB-TEST-01 - Checkout fails + wrong prices
Owner: Ola | Applies to: Shop.

1. Confirm the impact.
2. Review the CRM Bridge logs for auth_failure.
3. Reproduce on staging.
4. Get Incident Lead approval before any mitigation.

Safety rule: the assistant never disables the plugin itself.
"""
TRANSCRIPT = [
    {"speaker": "Kamil", "text": "Let's start the war room.", "at_s": 5},
    {"speaker": "Kamil", "text": "Atlas, have we seen this before?", "at_s": 20},
]


@pytest.fixture(autouse=True)
def env(monkeypatch, tmp_path):
    for k, v in {
        "OPENAI_API_KEY": "sk-test",
        "OPENAI_CHAT_MODEL": "test-model",
        "DATABASE_URL": "",
        "DEMO_TOKEN": DEMO,
        "AGENT_TOOLS": "true",
        "JIRA_BASE_URL": "",
        "JIRA_EMAIL": "",
        "JIRA_API_TOKEN": "",
        "JIRA_PROJECT_KEY": "",
        "DEMO_PROFILE": "acme",
    }.items():
        monkeypatch.setenv(k, v)
    get_settings.cache_clear()
    runtime.reset()
    msp = tmp_path / "msp"
    msp.mkdir()
    (msp / "incidents.json").write_text(json.dumps(INCIDENTS))
    (msp / "experts.json").write_text(json.dumps(EXPERTS))
    (msp / "runbook-rb-test-01.md").write_text(RUNBOOK)
    (msp / "client-novastore.md").write_text("# Client\nShop runs WooCommerce.")
    (msp / "expert-directory.md").write_text("# Experts\nOla knows Salesforce.")
    (msp / "brief.md").write_text("# INC-024\nPayments fail and prices are wrong.")
    (msp / "transcript_inc024.json").write_text(json.dumps(TRANSCRIPT))
    (msp / "slack-inc-011.md").write_text("not a prompt doc")
    (tmp_path / "api.md").write_text("# API\nRate limit is 50 rps.")
    monkeypatch.setattr(profile, "SEED_ROOT", tmp_path)
    profile._last = None  # noqa: SLF001
    profile.reset()
    llm._client = None
    orchestrator._busy.clear()
    yield
    runtime.reset()
    profile.reset()
    profile._last = None  # noqa: SLF001
    get_settings.cache_clear()
    llm._client = None


async def msp_on():
    await runtime.save({"DEMO_PROFILE": "msp"})


def client():
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")


# --- profile switch -------------------------------------------------------------------


async def test_profile_switch_resets_caches_and_validates():
    assert profile.current() == "acme"
    assert "Rate limit is 50 rps" in orchestrator.seed_docs()
    orchestrator._experts_cache = "- Dima: infra"  # noqa: SLF001
    factcheck._filter_cache = factcheck._filter()  # noqa: SLF001
    escalation._cache = [Expert(name="Dima")]  # noqa: SLF001
    async with client() as c:
        bad = await c.put("/settings", headers=AUTH, json={"DEMO_PROFILE": "nope"})
        ok = await c.put("/settings", headers=AUTH, json={"DEMO_PROFILE": "MSP"})
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "validation_error"
    assert ok.status_code == 200
    assert ok.json()["values"]["DEMO_PROFILE"]["value"] == "msp"
    assert profile.is_msp()
    assert orchestrator._experts_cache is None and escalation._cache is None  # noqa: SLF001
    assert factcheck._filter_cache is None  # noqa: SLF001
    docs = orchestrator.seed_docs()
    assert "Shop runs WooCommerce" in docs and "Ola knows Salesforce" in docs
    assert "Rate limit" not in docs and "not a prompt doc" not in docs
    assert await orchestrator.experts_text() == (
        "- Ola: salesforce, crm bridge\n- Marek: payment gateway\n- Kamil: owner, incident lead"
    )
    assert factcheck.worth_checking("Ola said so") and not factcheck.worth_checking("Dima said")
    # a value changed without PUT (e.g. another code path) is noticed too
    await runtime.save({"DEMO_PROFILE": "acme"})
    assert "Rate limit is 50 rps" in orchestrator.seed_docs()
    assert "Dima" in await orchestrator.experts_text()


async def test_msp_system_prompt_has_guardrails_and_owner():
    await msp_on()
    system = orchestrator.build_messages("brief", [], "Kamil", "q?", "- Ola: x")[0]["content"]
    assert "Kamil's delegate" in system  # the msp owner (Incident Lead), not OWNER_NAME
    assert "evidence, not a diagnosis" in system and "no data" in system
    assert "Incident Lead approves" in system and "that person's name" in system
    await runtime.save({"DEMO_PROFILE": "acme"})
    acme = orchestrator.build_messages("b", [], "Misha", "q?", "- Dima: x")[0]["content"]
    assert "Incident response rules" not in acme


# --- tools ------------------------------------------------------------------------------


async def test_msp_definitions():
    assert {t.get("name") for t in agent_tools.definitions()} >= {"search_knowledge"}
    await msp_on()
    defs = agent_tools.definitions()
    assert [d["name"] for d in defs] == [
        "find_similar_incidents",
        "get_incident",
        "get_runbook",
        "find_expert",
        "create_doc",
    ]
    assert all(d["type"] == "function" and d["strict"] for d in defs)
    for d in defs:
        params = d["parameters"]
        assert params["additionalProperties"] is False
        assert params["required"] == list(params["properties"])
    enum = defs[0]["parameters"]["properties"]["symptoms"]["items"]["enum"]
    assert enum == list(INCIDENTS["symptom_tags"])


async def test_find_similar_incidents_ranking():
    await msp_on()
    out = await agent_tools.find_similar_incidents(["payment_failure", "wrong_prices"])
    ids = [r["id"] for r in out["results"]]
    assert ids == ["INC-002", "INC-003", "INC-001"]  # full match, then overlap 1 by date desc
    top, promo, gateway = out["results"]
    assert top["verdict"] == "matches all reported symptoms" and top["missing"] == []
    assert top["matched"] == ["payment_failure", "wrong_prices"]
    assert gateway["verdict"].startswith("partial match: prices were correct")
    assert gateway["extra"] == ["gateway_auth_401"]
    assert promo["verdict"] == "partial match: no payment failure"
    assert len(top["quotes"]) == 3 and [q["time"] for q in top["quotes"]] == [
        "14:08",
        "14:12",
        "14:19",
    ]
    assert out["note"] == agent_tools.HISTORICAL_NOTE
    assert out["citations"][0] == 'INC-002 14:19 Ola: "Cause confirmed: token."'
    assert out["citations"][-1] == "RB-TEST-01 (runbook of INC-002)"
    # deterministic: same input, same output
    assert await agent_tools.find_similar_incidents(["wrong_prices", "payment_failure"]) == out


async def test_find_similar_incidents_bad_input():
    await msp_on()
    out = await agent_tools.find_similar_incidents(["nope"])
    assert "error" in out and "payment_failure" in out["known_tags"]
    raw = await agent_tools.execute(
        "find_similar_incidents", json.dumps({"symptoms": ["crm_sync_delay"]})
    )
    assert [r["id"] for r in json.loads(raw)["results"]] == ["INC-004"]


async def test_get_incident():
    await msp_on()
    ok = await agent_tools.get_incident("inc-2")
    assert ok["id"] == "INC-002" and len(ok["quotes"]) == 4
    assert ok["citations"][0].startswith("INC-002 14:19 Ola")
    bad = await agent_tools.get_incident("INC-999")
    assert "unknown incident" in bad["error"]
    assert bad["known_ids"] == ["INC-001", "INC-002", "INC-003", "INC-004"]


async def test_get_runbook():
    await msp_on()
    rb = await agent_tools.get_runbook("safe checks before a change")
    assert rb["id"] == "RB-TEST-01" and rb["owner"] == "Ola"
    assert len(rb["steps"]) == 4 and rb["steps"][3].startswith("4. Get Incident Lead approval")
    assert rb["safety_rule"].startswith("Safety rule:")
    assert rb["citations"] == ["RB-TEST-01 steps 1-4, owner Ola"]


async def test_find_expert_reachable_flag():
    await msp_on()
    out = await agent_tools.find_expert("Salesforce integration")
    (ola,) = out["experts"]
    assert ola["name"] == "Ola" and ola["resolved"] == ["INC-002"] and ola["reachable"] is True
    assert out["citations"] == ["expert-directory: Ola (resolved INC-002)"]
    marek = (await agent_tools.find_expert("payment gateway"))["experts"][0]
    assert marek["name"] == "Marek" and marek["reachable"] is False  # no email / chat id
    kamil = (await agent_tools.find_expert("who approves mitigation"))["experts"][0]
    assert kamil["name"] == "Kamil" and kamil["approves"] is True


# --- call path: citations to the chat ---------------------------------------------------


@pytest.fixture
def world(monkeypatch):
    w = {"said": [], "chat": [], "hook": []}

    async def get_meeting_mode(meeting_id):
        return "delegate"

    async def get_brief(meeting_id):
        return "INC-024: payments fail, prices wrong."

    async def get_recent_utterances(meeting_id, since_ts, limit=200):
        return []

    async def insert_agent_said(meeting_id, text, ts, in_reply_to=None):
        return {"id": "as_1"}

    async def say(meeting_id, text):
        w["said"].append(text)
        return True

    async def say_filler(meeting_id):
        return True

    async def publish(meeting_id, type_, data):
        return 1

    async def get_meeting(meeting_id):
        return {"id": meeting_id, "recall_bot_id": "bot_1"}

    async def send_chat_message(bot_id, text):
        w["chat"].append(text)
        return True

    async def hook(meeting_id, question, topic, asked_by):
        w["hook"].append(topic)
        return {"expert": "Ola", "escalation_id": "esc_1"}

    monkeypatch.setattr(db, "get_meeting_mode", get_meeting_mode)
    monkeypatch.setattr(db, "get_brief", get_brief)
    monkeypatch.setattr(db, "get_recent_utterances", get_recent_utterances)
    monkeypatch.setattr(db, "insert_agent_said", insert_agent_said)
    monkeypatch.setattr(db, "get_meeting", get_meeting)
    monkeypatch.setattr(recall, "send_chat_message", send_chat_message)
    monkeypatch.setattr(speech, "say", say)
    monkeypatch.setattr(speech, "say_filler", say_filler)
    monkeypatch.setattr(hub, "publish", publish)
    monkeypatch.setattr(orchestrator, "on_needs_expert", hook)
    monkeypatch.setattr(agent_voice, "is_speaking", lambda mid: False)
    return w


def _resp(rid, output):
    return httpx.Response(200, json={"id": rid, "object": "response", "output": output})


def _fcall(name, args):
    item = {"type": "function_call", "id": "fc_1", "call_id": "call_1", "name": name}
    return _resp("resp_1", [{**item, "arguments": json.dumps(args)}])


def _final(answer, needs_expert=False, topic=""):
    content = json.dumps(
        {"answer": answer, "confidence": 0.9, "needs_expert": needs_expert, "topic": topic}
    )
    msg = {"type": "output_text", "text": content, "annotations": []}
    return _resp("resp_2", [{"type": "message", "role": "assistant", "content": [msg]}])


def _utt(text):
    return {"id": "u_1", "speaker": "Kamil", "text": text, "ts": 60}


async def _drain():
    import asyncio

    if orchestrator._bg:  # noqa: SLF001
        await asyncio.gather(*list(orchestrator._bg))  # noqa: SLF001


@respx.mock
async def test_msp_citations_posted_to_chat(world):
    await msp_on()
    route = respx.post(RESP_URL).mock(
        side_effect=[
            _fcall("find_similar_incidents", {"symptoms": ["payment_failure", "wrong_prices"]}),
            _final("Yes, INC-002 at 14:19: an expired CRM token; for INC-024 it's a hypothesis."),
        ]
    )
    q = "have we seen payments failing with wrong prices?"
    assert await orchestrator.ask(MID, _utt(f"Atlas, {q}"), q)
    await _drain()

    first, second = (json.loads(c.request.content) for c in route.calls)
    assert [t["name"] for t in first["tools"]][0] == "find_similar_incidents"
    assert all(t["type"] == "function" for t in first["tools"])  # no web_search on msp
    assert "include" not in first
    system = first["input"][0]["content"]
    assert "Incident response rules" in system and "find_similar_incidents:" in system
    assert "web_search:" not in system
    out = json.loads(second["input"][0]["output"])
    assert out["results"][0]["id"] == "INC-002"
    assert world["said"][0].startswith("Yes, INC-002 at 14:19")
    (line,) = world["chat"]
    assert line.startswith('Sources: INC-002 14:19 Ola: "Cause confirmed: token."')
    assert line.count(" | ") == 2 and len(line) <= orchestrator.CHAT_MAX_CHARS


@respx.mock
async def test_msp_no_citations_when_escalated(world):
    await msp_on()
    respx.post(RESP_URL).mock(
        side_effect=[
            _fcall("find_expert", {"topic": "Salesforce"}),
            _final("", needs_expert=True, topic="Ola"),
        ]
    )
    q = "ask Ola whether the token expired"
    assert await orchestrator.ask(MID, _utt(f"Atlas, {q}"), q)
    await _drain()
    assert world["hook"] == ["Ola"] and world["chat"] == []
    assert world["said"] == ["Sure, asking Ola on Slack now."]


def test_sources_text_cap_and_acme_format():
    assert orchestrator.sources_text(["https://a.io", "https://b.io"], []) == (
        "Sources: https://a.io https://b.io"
    )
    assert orchestrator.sources_text([], []) == ""
    long = orchestrator.source_refs(["x" * 400, "y" * 400, "z" * 400, "w"])
    text = orchestrator.sources_text([], long)
    assert len(text) <= 500 and len(long) == 3


@respx.mock
async def test_answer_question_returns_meta_without_speaking(world):
    await msp_on()
    respx.post(RESP_URL).mock(
        side_effect=[
            _fcall("get_runbook", {"query": "safe checks"}),
            _final("Check the logs, reproduce on staging, then get approval (RB-TEST-01)."),
        ]
    )
    result, meta = await orchestrator.answer_question("safest checks?", brief="INC-024")
    assert result["answer"].startswith("Check the logs") and not orchestrator.is_escalated(result)
    assert meta["tools"] == ["get_runbook"] and meta["refs"] == ["RB-TEST-01 steps 1-4, owner Ola"]
    assert world["said"] == [] and world["chat"] == []


# --- Jira, named expert -------------------------------------------------------------------


async def test_jira_skips_incident_ids_on_msp(monkeypatch):
    for k, v in {
        "JIRA_BASE_URL": "https://acme.atlassian.net",
        "JIRA_EMAIL": "a@b.c",
        "JIRA_API_TOKEN": "t",
        "JIRA_PROJECT_KEY": "PTW",
    }.items():
        monkeypatch.setenv(k, v)
    get_settings.cache_clear()
    asked = []

    async def get_issue(key):
        asked.append(key)
        return None

    monkeypatch.setattr(jira, "get_issue", get_issue)
    await msp_on()
    assert await orchestrator.jira_context("what was the cause of INC-002?") == []
    found = await orchestrator.jira_context("is INC-002 related to PTW-5?")
    assert asked == ["PTW-5"] and found == [{"key": "PTW-5", "not_found": True}]
    asked.clear()
    await runtime.save({"DEMO_PROFILE": "acme"})
    await orchestrator.jira_context("what about INC-002?")
    assert asked == ["INC-2"]  # acme: unchanged behaviour


def test_match_expert_by_name_first():
    experts = [
        Expert(name="Ola", topics=["salesforce"]),
        Expert(name="Marek", topics=["payment gateway"]),
        Expert(name="Kamil", topics=["owner"], is_owner=True),
    ]
    assert escalation.match_expert("Ola", experts).name == "Ola"
    assert escalation.match_expert("ask marek", experts).name == "Marek"
    assert escalation.match_expert("owner", experts, "Can you ask Ola about it?").name == "Ola"
    assert escalation.match_expert("payment gateway", experts).name == "Marek"
    assert escalation.match_expert("Olaf's area", experts).name == "Kamil"  # whole word only


# --- experts per profile -------------------------------------------------------------------


class FakeDB:
    def __init__(self):
        self.rows: dict[str, dict] = {}
        self.n = 0
        self.upserts: list[list[dict]] = []

    def _out(self, r):
        return {**r, "is_owner": "owner" in r["topics"]}

    def add(self, name, topics, **kw):
        self.n += 1
        r = {"id": f"ex_{self.n}", "name": name, "role": "", "topics": list(topics),
             "channel": "slack", "email": kw.get("email"), "slack_user_id": None,
             "telegram_chat_id": None}  # fmt: skip
        self.rows[r["id"]] = r
        return r

    async def list_experts(self):
        return [self._out(r) for r in self.rows.values()]

    async def get_expert(self, expert_id):
        r = self.rows.get(expert_id)
        return self._out(r) if r else None

    async def insert_expert(self, e):
        return self._out(self.add(e["name"], e.get("topics") or [], email=e.get("email")))

    async def update_expert(self, expert_id, **fields):
        self.rows[expert_id].update(fields)
        return self._out(self.rows[expert_id])

    async def upsert_experts(self, items):
        self.upserts.append(items)
        for e in items:
            topics = list(e.get("topics") or []) + (["owner"] if e.get("is_owner") else [])
            self.add(e["name"], topics, email=e.get("email"))


@pytest.fixture
def fake(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://fake")
    get_settings.cache_clear()
    f = FakeDB()
    for name in ("list_experts", "get_expert", "insert_expert", "update_expert", "upsert_experts"):
        monkeypatch.setattr(db, name, getattr(f, name))

    async def no_setting(*a):
        return None

    monkeypatch.setattr(db, "upsert_setting", no_setting)
    monkeypatch.setattr(db, "delete_setting", no_setting)
    escalation._cache = None  # noqa: SLF001
    return f


async def test_experts_filtered_and_tagged_per_profile(fake):
    fake.add("Dima", ["infra"])
    fake.add("Ola", ["salesforce", "profile:msp"], email="ola@example.com")
    async with client() as c:
        acme = (await c.get("/experts", headers=AUTH)).json()["items"]
        await msp_on()
        msp = (await c.get("/experts", headers=AUTH)).json()["items"]
        created = await c.post(
            "/experts", headers=AUTH, json={"name": "Marek", "topics": ["php"], "is_owner": True}
        )
        upd = await c.put("/experts/ex_3", headers=AUTH, json={"topics": ["api"]})
    assert [(e["name"], e["profile"]) for e in acme] == [("Dima", "acme")]
    assert [(e["name"], e["topics"], e["profile"]) for e in msp] == [("Ola", ["salesforce"], "msp")]
    body = created.json()
    assert body["topics"] == ["php"] and body["profile"] == "msp" and body["is_owner"] is True
    assert fake.rows["ex_3"]["topics"] == ["api", "profile:msp", "owner"]  # tag kept on edit
    assert upd.json()["topics"] == ["api"]
    names = [e.name for e in await escalation.load_experts(refresh=True)]
    assert names == ["Ola", "Marek"]
    assert all("profile:msp" not in e.topics for e in escalation._cache)  # noqa: SLF001


async def test_seed_msp_experts_idempotent(fake):
    fake.add("Dima", ["infra"])
    assert await escalation.seed_msp_experts() == 3
    (items,) = fake.upserts
    assert all("profile:msp" in e["topics"] for e in items)
    assert await escalation.seed_msp_experts() == 0  # msp experts exist: never reseeded
    await escalation.seed_experts()  # acme still has Dima: nothing seeded
    assert len(fake.upserts) == 1
    await msp_on()
    owner = escalation.match_expert("", await escalation.load_experts())
    assert owner.name == "Kamil"  # owner fallback per profile


# --- meetings, simulate ----------------------------------------------------------------


@pytest.fixture
def store(monkeypatch):
    briefs = []

    async def insert_meeting(**kw):
        return {"id": "m_01", "recall_bot_id": None, **kw}

    async def update_meeting(mid, **kw):
        return {"id": mid, **kw}

    async def insert_brief(mid, text):
        briefs.append(text)

    monkeypatch.setattr(db, "insert_meeting", insert_meeting)
    monkeypatch.setattr(db, "update_meeting", update_meeting)
    monkeypatch.setattr(db, "insert_brief", insert_brief)
    monkeypatch.setenv("RECALL_API_KEY", "rk_test")
    monkeypatch.setenv("RECALL_BASE_URL", RECALL)
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://crew.example.com")
    monkeypatch.setenv("WEBHOOK_TOKEN", "wh-t")
    get_settings.cache_clear()
    return briefs


@respx.mock
async def test_meetings_default_brief_on_msp(store):
    respx.post(f"{RECALL}/api/v1/bot/").mock(return_value=httpx.Response(201, json={"id": "bot_1"}))
    body = {"meeting_url": "https://meet.google.com/abc-defg-hij", "mode": "delegate"}
    async with client() as c:
        await c.post("/meetings", headers=AUTH, json=body)  # acme: no default brief
        await msp_on()
        await c.post("/meetings", headers=AUTH, json=body)
        await c.post("/meetings", headers=AUTH, json={**body, "brief": "Own brief"})
        await c.post("/meetings", headers=AUTH, json={**body, "mode": "notetaker"})
    assert store == ["# INC-024\nPayments fail and prices are wrong.", "Own brief"]


async def test_simulate_fixture_per_profile(tmp_path):
    acme = [{"speaker": "Misha", "text": "Atlas, what did Artem finish?", "at_s": 1}]
    (tmp_path / "demo_transcript.json").write_text(json.dumps(acme))
    assert simulate.load_lines() == acme
    assert profile.sim_title() == "Simulated stand-up"
    assert simulate.resolve_reply(...) == "Thursday"
    await msp_on()
    assert simulate.load_lines() == TRANSCRIPT
    assert profile.sim_title() == "INC-024 NovaStore SEV1 war room"
    assert simulate.resolve_reply(...).startswith("Check the CRM Bridge logs")
    assert simulate.resolve_reply(None) is None and simulate.resolve_reply("x") == "x"
    assert profile.sim_brief().startswith("# INC-024")

"""Escalation loop (M3.3a): fake DB / notifier / voice / Recall, real escalation logic."""

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
import respx

from app import db, escalation, hub, llm, orchestrator, rag, recall, speech
from app.config import get_settings
from app.notifier import base as notifier_base
from app.notifier.base import Expert, NotifierError, SentMessage

ROOT = Path(__file__).resolve().parents[2]
OPENAI_URL = "https://api.openai.com/v1/chat/completions"
MID = "m_01"
DM = "D_DIMA"
THREAD = "1730000000.000100"
QUESTION = "when do we migrate to Postgres 17?"

EXPERTS = [
    Expert(name="Dima", topics=["postgres", "infra"], email="dima@example.com", id="ex_dima"),
    Expert(name="Artem", topics=["owner"], email="artem@example.com", is_owner=True, id="ex_a"),
]


def mock(name):
    return json.loads((ROOT / "mocks" / name).read_text())


class FakeNotifier:
    def __init__(self, fail=False):
        self.fail = fail
        self.questions = []
        self.replies = []

    async def send_question(self, expert, *, meeting_title, asked_by, question, context_lines):
        self.questions.append(
            {
                "expert": expert.name,
                "meeting_title": meeting_title,
                "asked_by": asked_by,
                "question": question,
                "context_lines": context_lines,
            }
        )
        if self.fail:
            raise NotifierError("slack users.lookupByEmail: users_not_found")
        return SentMessage(channel="slack", external_msg_id=THREAD, external_channel_id=DM)

    async def post_reply(self, sent, text):
        self.replies.append((sent.external_channel_id, sent.external_msg_id, text))


@pytest.fixture(autouse=True)
def env(monkeypatch):
    for k, v in {
        "OPENAI_API_KEY": "sk-test",
        "OPENAI_CHAT_MODEL": "test-model",
        "SLACK_BOT_TOKEN": "xoxb-test",
        "DATABASE_URL": "",
    }.items():
        monkeypatch.setenv(k, v)
    get_settings.cache_clear()
    llm._client = None
    orchestrator._busy.clear()
    monkeypatch.setattr(escalation, "ESCALATION_TIMEOUT_S", 30.0)
    monkeypatch.setattr(escalation, "_cache", list(EXPERTS))
    yield
    for t in list(escalation._tasks):
        t.cancel()
    escalation._timeouts.clear()
    get_settings.cache_clear()
    llm._client = None


@pytest.fixture
def world(monkeypatch):
    """In-memory DB with the same semantics as the SQL helpers, plus fake voice/hub/Recall."""
    w = {
        "meeting": {
            "id": MID,
            "title": "Q4 infra sync",
            "status": "in_call",
            "mode": "delegate",
            "recall_bot_id": "bot_1",
            "started_at": datetime.now(UTC),
            "action_items": [],
        },
        "utterances": [
            {"id": "u1", "speaker": "Misha", "text": "Morning!", "ts_start": 300.0},
            {"id": "u2", "speaker": "Julian", "text": "Billing page is done.", "ts_start": 320.0},
            {"id": "u3", "speaker": "Misha", "text": "Great.", "ts_start": 330.0},
            {"id": "u4", "speaker": "Julian", "text": f"Crew, {QUESTION}", "ts_start": 340.0},
        ],
        "esc": {},
        "facts": [],
        "agent_said": [],
        "said": [],
        "chat": [],
        "events": [],
        "notifier": FakeNotifier(),
    }

    def with_expert(r):
        name = next((e.name for e in EXPERTS if e.id == r["expert_id"]), None)
        return {**r, "expert": name}

    async def get_meeting(meeting_id):
        return dict(w["meeting"]) if meeting_id == MID else None

    async def get_meeting_mode(meeting_id):
        return w["meeting"]["mode"]

    async def get_brief(meeting_id):
        return ""

    async def get_recent_utterances(meeting_id, since_ts, limit=200):
        return [u for u in w["utterances"] if u["ts_start"] >= since_ts]

    async def get_last_utterances(meeting_id, n=3):
        return w["utterances"][-n:]

    async def insert_escalation(*, meeting_id, expert_id, channel, question, asked_by, ts):
        eid = f"esc_{len(w['esc']) + 1:02d}"
        w["esc"][eid] = {
            "id": eid,
            "meeting_id": meeting_id,
            "expert_id": expert_id,
            "channel": channel,
            "question": question,
            "asked_by": asked_by,
            "ts": ts,
            "external_msg_id": None,
            "external_channel_id": None,
            "answer": None,
            "status": "waiting",
            "asked_at": datetime.now(UTC),
            "answered_ts": None,
        }
        return with_expert(w["esc"][eid])

    async def set_escalation_external(eid, msg_id, channel_id):
        w["esc"][eid].update(external_msg_id=msg_id, external_channel_id=channel_id)

    async def get_escalation_by_external(msg_id, channel_id=None):
        for r in w["esc"].values():
            if r["external_msg_id"] == msg_id and r["external_channel_id"] in (None, channel_id):
                return with_expert(r)
        return None

    async def answer_escalation(eid, answer, answered_ts):
        r = w["esc"].get(eid)
        if r is None or r["status"] == "answered":
            return None
        prev = r["status"]
        r.update(answer=answer, answered_ts=answered_ts, status="answered")
        return {**with_expert(r), "prev_status": prev}

    async def timeout_escalation(eid):
        r = w["esc"].get(eid)
        if r is None or r["status"] != "waiting":
            return None
        r["status"] = "timeout"
        return with_expert(r)

    async def append_action_item(meeting_id, item):
        w["meeting"]["action_items"].append(item)

    async def insert_fact(meeting_id, speaker, text, kind):
        row = {"id": f"f{len(w['facts'])}", "speaker": speaker, "text": text, "kind": kind}
        w["facts"].append(row)
        return row

    async def insert_agent_said(meeting_id, text, ts, in_reply_to=None):
        row = {"id": f"as_{len(w['agent_said']) + 1:02d}", "text": text, "ts": ts}
        row["in_reply_to"] = in_reply_to
        w["agent_said"].append(row)
        return row

    async def say(meeting_id, text):
        w["said"].append(text)
        return True

    async def say_filler(meeting_id):
        return True

    async def send_chat_message(bot_id, text):
        w["chat"].append((bot_id, text))
        return True

    async def publish(meeting_id, type_, data):
        w["events"].append(hub.envelope(meeting_id, type_, data))
        return 1

    for name, fn in {
        "get_meeting": get_meeting,
        "get_meeting_mode": get_meeting_mode,
        "get_brief": get_brief,
        "get_recent_utterances": get_recent_utterances,
        "get_last_utterances": get_last_utterances,
        "insert_escalation": insert_escalation,
        "set_escalation_external": set_escalation_external,
        "get_escalation_by_external": get_escalation_by_external,
        "answer_escalation": answer_escalation,
        "timeout_escalation": timeout_escalation,
        "append_action_item": append_action_item,
        "insert_fact": insert_fact,
        "insert_agent_said": insert_agent_said,
    }.items():
        monkeypatch.setattr(db, name, fn)
    monkeypatch.setattr(speech, "say", say)
    monkeypatch.setattr(speech, "say_filler", say_filler)
    monkeypatch.setattr(recall, "send_chat_message", send_chat_message)
    monkeypatch.setattr(hub, "publish", publish)
    monkeypatch.setitem(notifier_base.NOTIFIERS, "slack", w["notifier"])
    return w


def events(w, type_):
    return [e for e in w["events"] if e["type"] == type_]


async def settle():
    for _ in range(5):
        await asyncio.sleep(0)


async def start(world):
    res = await escalation.start(MID, QUESTION, "postgres", "Julian")
    await settle()
    return res


async def test_happy_path(world, monkeypatch):
    res = await start(world)
    assert res == {"expert": "Dima", "escalation_id": "esc_01"}

    created = events(world, "escalation_created")
    m = mock("ws_escalation_created.json")
    assert len(created) == 1 and created[0].keys() == m.keys()
    assert created[0]["data"].keys() == m["data"].keys()
    assert created[0]["data"] == {
        "id": "esc_01",
        "expert": "Dima",
        "channel": "slack",
        "question": QUESTION,
        "asked_by": "Julian",
        "ts": 340,
        "status": "waiting",
        "answer": None,
        "answered_ts": None,
    }
    q = world["notifier"].questions
    assert len(q) == 1 and q[0]["meeting_title"] == "Q4 infra sync"
    assert q[0]["context_lines"] == [
        "Julian: Billing page is done.",
        "Misha: Great.",
        f"Julian: Crew, {QUESTION}",
    ]
    assert world["esc"]["esc_01"]["external_msg_id"] == THREAD
    assert "esc_01" in escalation._timeouts

    calls = []
    monkeypatch.setattr(rag, "backfill_later", lambda: calls.append(1))
    await escalation.on_expert_reply(DM, THREAD, "Thursday", "U_DIMA")
    await settle()
    assert calls == [1]

    assert world["said"] == ["Dima says: Thursday"]
    assert world["chat"] == [("bot_1", "Dima says: Thursday")]
    said = events(world, "agent_said")
    assert said[0]["data"]["in_reply_to"] == "esc_01"
    assert said[0]["data"]["text"] == "Dima says: Thursday"
    assert world["agent_said"][0]["in_reply_to"] == "esc_01"
    assert world["facts"] == [
        {"id": "f0", "speaker": "Dima", "text": f"Q: {QUESTION}\nA: Thursday", "kind": "answer"}
    ]
    answered = events(world, "escalation_answered")
    m = mock("ws_escalation_answered.json")
    assert len(answered) == 1 and answered[0]["data"].keys() == m["data"].keys()
    assert answered[0]["data"]["status"] == "answered"
    assert answered[0]["data"]["answer"] == "Thursday"
    assert isinstance(answered[0]["data"]["answered_ts"], int)
    assert answered[0]["data"]["answered_ts"] >= 340
    assert world["notifier"].replies == [(DM, THREAD, escalation.THANKS_LIVE)]
    assert "esc_01" not in escalation._timeouts  # timeout cancelled
    assert world["meeting"]["action_items"] == []


async def test_duplicate_reply_ignored(world):
    await start(world)
    await escalation.on_expert_reply(DM, THREAD, "Thursday", "U_DIMA")
    await escalation.on_expert_reply(DM, THREAD, "Actually Friday", "U_DIMA")
    await settle()
    assert world["said"] == ["Dima says: Thursday"]
    assert len(events(world, "escalation_answered")) == 1
    assert len(world["notifier"].replies) == 1
    assert world["esc"]["esc_01"]["answer"] == "Thursday"


async def test_timeout(world, monkeypatch):
    monkeypatch.setattr(escalation, "ESCALATION_TIMEOUT_S", 0.1)
    await start(world)
    await asyncio.sleep(0.3)

    assert world["said"] == ["Dima hasn't answered yet — I've added it to follow-ups."]
    assert world["chat"] == []
    assert world["meeting"]["action_items"] == [{"owner": "Dima", "text": QUESTION, "due": None}]
    timeout = events(world, "escalation_answered")
    m = mock("ws_escalation_timeout.json")
    assert len(timeout) == 1 and timeout[0]["data"].keys() == m["data"].keys()
    assert timeout[0]["data"]["status"] == "timeout"
    assert timeout[0]["data"]["answer"] is None and timeout[0]["data"]["answered_ts"] is None
    assert world["esc"]["esc_01"]["status"] == "timeout"
    assert "esc_01" not in escalation._timeouts


async def test_late_reply_after_timeout(world, monkeypatch):
    monkeypatch.setattr(escalation, "ESCALATION_TIMEOUT_S", 0.05)
    await start(world)
    await asyncio.sleep(0.2)
    world["meeting"]["status"] = "done"
    world["said"].clear()

    await escalation.on_expert_reply(DM, THREAD, "Thursday", "U_DIMA")
    assert world["said"] == [] and world["chat"] == []
    assert world["esc"]["esc_01"]["status"] == "answered"
    assert world["esc"]["esc_01"]["answer"] == "Thursday"
    answered = events(world, "escalation_answered")
    assert [e["data"]["status"] for e in answered] == ["timeout", "answered"]
    assert answered[-1]["data"]["answer"] == "Thursday"
    assert world["notifier"].replies == [(DM, THREAD, escalation.THANKS_ENDED)]


async def test_late_reply_call_still_running_not_spoken(world, monkeypatch):
    monkeypatch.setattr(escalation, "ESCALATION_TIMEOUT_S", 0.05)
    await start(world)
    await asyncio.sleep(0.2)
    world["said"].clear()
    await escalation.on_expert_reply(DM, THREAD, "Thursday", "U_DIMA")
    assert world["said"] == []
    assert world["esc"]["esc_01"]["status"] == "answered"
    assert world["notifier"].replies[-1][2] == escalation.THANKS_LATE


async def test_reply_after_call_ended_not_spoken(world):
    await start(world)
    world["meeting"]["status"] = "done"
    await escalation.on_expert_reply(DM, THREAD, "Thursday", "U_DIMA")
    assert world["said"] == [] and world["facts"] == []
    assert events(world, "escalation_answered")[0]["data"]["status"] == "answered"
    assert world["notifier"].replies == [(DM, THREAD, escalation.THANKS_ENDED)]


async def test_unknown_thread_ignored(world):
    await start(world)
    await escalation.on_expert_reply(DM, "999.000", "Thursday", "U_DIMA")
    await escalation.on_expert_reply("D_OTHER", THREAD, "Thursday", "U_X")
    assert world["said"] == []
    assert events(world, "escalation_answered") == []
    assert world["notifier"].replies == []
    assert world["esc"]["esc_01"]["status"] == "waiting"


async def test_notifier_failure_still_times_out(world, monkeypatch):
    world["notifier"].fail = True
    monkeypatch.setattr(escalation, "ESCALATION_TIMEOUT_S", 0.1)
    res = await start(world)
    assert res["escalation_id"] == "esc_01"
    assert len(world["notifier"].questions) == 1
    assert world["esc"]["esc_01"]["external_msg_id"] is None
    await asyncio.sleep(0.3)
    assert world["esc"]["esc_01"]["status"] == "timeout"
    assert events(world, "escalation_answered")[0]["data"]["status"] == "timeout"
    assert world["meeting"]["action_items"][0]["owner"] == "Dima"


async def test_no_notifier_still_times_out(world, monkeypatch):
    monkeypatch.delitem(notifier_base.NOTIFIERS, "slack")
    monkeypatch.setattr(escalation, "ESCALATION_TIMEOUT_S", 0.1)
    assert (await start(world))["expert"] == "Dima"
    await asyncio.sleep(0.3)
    assert world["esc"]["esc_01"]["status"] == "timeout"


async def test_start_returns_before_slack_io(world, monkeypatch):
    gate = asyncio.Event()

    async def slow_send(*a, **kw):
        await gate.wait()
        return SentMessage(channel="slack", external_msg_id=THREAD, external_channel_id=DM)

    monkeypatch.setattr(world["notifier"], "send_question", slow_send)
    res = await asyncio.wait_for(escalation.start(MID, QUESTION, "postgres", "Julian"), 0.5)
    assert res["expert"] == "Dima"
    assert world["esc"]["esc_01"]["external_msg_id"] is None
    gate.set()
    await settle()
    assert world["esc"]["esc_01"]["external_msg_id"] == THREAD


async def test_start_db_failure_returns_none(world, monkeypatch):
    async def boom(**kw):
        raise RuntimeError("DATABASE_URL is not set")

    monkeypatch.setattr(db, "insert_escalation", boom)
    assert await escalation.start(MID, QUESTION, "postgres", "Julian") is None
    assert world["events"] == [] and escalation._timeouts == {}


def completion(answer="", confidence=0.2, needs_expert=True, topic="postgres"):
    content = json.dumps(
        {"answer": answer, "confidence": confidence, "needs_expert": needs_expert, "topic": topic}
    )
    return httpx.Response(
        200,
        json={
            "id": "chatcmpl-1",
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


@respx.mock
async def test_orchestrator_says_asking_dima_with_escalation_id(world):
    respx.post(OPENAI_URL).mock(return_value=completion())
    utt = {"id": "u4", "speaker": "Julian", "text": f"Crew, {QUESTION}", "ts": 340}
    await orchestrator.handle(MID, utt)
    await settle()

    assert world["said"] == ["I don't know, asking Dima now."]
    assert world["agent_said"][0]["in_reply_to"] == "esc_01"
    said = events(world, "agent_said")
    assert said[0]["data"]["in_reply_to"] == "esc_01"
    assert [e["type"] for e in world["events"]] == ["escalation_created", "agent_said"]
    assert world["notifier"].questions[0]["asked_by"] == "Julian"

    await escalation.on_expert_reply(DM, THREAD, "Thursday", "U_DIMA")
    assert world["said"][-1] == "Dima says: Thursday"

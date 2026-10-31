import asyncio
import json
import logging
from pathlib import Path

import httpx
import pytest
import respx

from app import agent_voice, db, hub, llm, orchestrator, speech, webhooks_recall
from app.config import get_settings

ROOT = Path(__file__).resolve().parents[2]
OPENAI_URL = "https://api.openai.com/v1/chat/completions"
MID = "m_01"


@pytest.fixture(autouse=True)
def env(monkeypatch):
    for k, v in {
        "OPENAI_API_KEY": "sk-test",
        "OPENAI_CHAT_MODEL": "test-model",
        "DATABASE_URL": "",
    }.items():
        monkeypatch.setenv(k, v)
    get_settings.cache_clear()
    llm._client = None
    orchestrator._busy.clear()
    orchestrator._armed.clear()
    yield
    get_settings.cache_clear()
    llm._client = None


@pytest.fixture
def world(monkeypatch):
    """Fake DB, voice and hub. Records what the agent says and publishes."""
    w = {"mode": "delegate", "said": [], "fillers": 0, "events": [], "rows": [], "hook": []}

    async def get_meeting_mode(meeting_id):
        return w["mode"]

    async def get_brief(meeting_id):
        return "Artem finished the Slack escalation flow. He cannot promise dates."

    async def get_recent_utterances(meeting_id, since_ts, limit=200):
        w["since"] = since_ts
        return [{"id": "u_1", "speaker": "Misha", "text": "Morning!", "ts_start": 12.0}]

    async def insert_agent_said(meeting_id, text, ts, in_reply_to=None):
        row = {
            "id": "as_01",
            "meeting_id": meeting_id,
            "text": text,
            "ts": ts,
            "in_reply_to": in_reply_to,
        }
        w["rows"].append(row)
        return row

    async def say(meeting_id, text):
        w["said"].append(text)
        return True

    async def say_filler(meeting_id):
        w["fillers"] += 1
        w["said"].append("<filler>")
        return True

    async def publish(meeting_id, type_, data):
        w["events"].append(hub.envelope(meeting_id, type_, data))
        return 1

    async def hook(meeting_id, question, topic, asked_by):
        w["hook"].append((meeting_id, question, topic, asked_by))
        return w.get("hook_return")

    monkeypatch.setattr(db, "get_meeting_mode", get_meeting_mode)
    monkeypatch.setattr(db, "get_brief", get_brief)
    monkeypatch.setattr(db, "get_recent_utterances", get_recent_utterances)
    monkeypatch.setattr(db, "insert_agent_said", insert_agent_said)
    monkeypatch.setattr(speech, "say", say)
    monkeypatch.setattr(speech, "say_filler", say_filler)
    monkeypatch.setattr(hub, "publish", publish)
    monkeypatch.setattr(orchestrator, "on_needs_expert", hook)
    monkeypatch.setattr(agent_voice, "is_speaking", lambda mid: w.get("speaking", False))
    return w


def completion(
    answer="Artem finished the Slack escalation flow.", confidence=0.9, needs_expert=False, topic=""
):
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


def utt(text, speaker="Misha", ts=382):
    return {"id": "u_9", "speaker": speaker, "text": text, "ts": ts}


@pytest.mark.parametrize(
    "text,question",
    [
        ("Atlas, what did Artem finish?", "what did Artem finish?"),
        ("atlas what did Artem finish", "what did Artem finish"),
        ("ATLAS: what is the status?", "what is the status?"),
        ("Okay so Atlas, what did Artem finish?", "what did Artem finish?"),
        ("blah. Atlas, when do we migrate to Postgres 17?", "when do we migrate to Postgres 17?"),
        ("Hey Atlas what is our API limit", "what is our API limit"),
        ("At last, what did Artem finish", "what did Artem finish"),
        ("ok atlas, deploy status?", "deploy status?"),
        ("Okay Atlas, deploy status?", "deploy status?"),
        ("Atlass, deploy status?", "deploy status?"),
        ("atlis deploy status", "deploy status"),
        ("... Atlas, deploy status?", "deploy status?"),
        ('"Atlas, deploy status?"', 'deploy status?"'),
        ("one two three four five Atlas, deploy status?", "deploy status?"),  # 6th word
        ("Atlas is covering today", "is covering today"),  # no question-word requirement
    ],
)
def test_trigger_positive(text, question):
    assert orchestrator.parse_trigger(text) == question


@pytest.mark.parametrize(
    "text",
    [
        "Atlas",
        "Atlas,",
        "Atlas?",
        "Atlas, status?",  # one word is not a question
        "hey atlas",
        "we finally made it at last",
        "so at last, what did we finish",  # "at last" only as the first words
        "one two three four five six Atlas, deploy status?",  # 7th word
        "Morning! Artem is out today, so his AI delegate Atlas covers for him.",
        "Atlases are heavy books",
        "Atlas\u2019s notes are great",
        "Crew, what did Artem finish?",  # the old wake word is gone
        "",
    ],
)
def test_trigger_negative(text):
    assert orchestrator.parse_trigger(text) is None


def test_match_trigger_reasons():
    assert orchestrator.match_trigger("hello there")[1] == "no wake word"
    assert "word 7" in orchestrator.match_trigger("a b c d e f Atlas, what is up")[1]
    assert "shorter" in orchestrator.match_trigger("Atlas, status?")[1]


def test_aliases_built_from_agent_name(monkeypatch):
    assert orchestrator.wake_aliases("Atlas") == (
        "hey atlas",
        "okay atlas",
        "ok atlas",
        "atlas",
        "atlass",
        "atlis",
    )
    monkeypatch.setenv("AGENT_NAME", "Nova")
    get_settings.cache_clear()
    assert orchestrator.parse_trigger("Nova, what is our API limit?") == "what is our API limit?"
    assert orchestrator.parse_trigger("Atlas, what is our API limit?") is None


async def test_live_transcript_is_logged_with_reason(world, caplog):
    with caplog.at_level(logging.INFO, logger="app.orchestrator"):
        await orchestrator.handle(MID, utt("we finally made it at last"))
    assert "utterance m_01 Misha: we finally made it at last" in caplog.text
    assert "no trigger in m_01: no wake word" in caplog.text


@respx.mock
async def test_normal_answer_path(world):
    route = respx.post(OPENAI_URL).mock(return_value=completion())
    await orchestrator.handle(MID, utt("Atlas, what did Artem finish this week?"))

    assert world["said"] == ["Artem finished the Slack escalation flow."]
    assert world["hook"] == []
    assert world["since"] == pytest.approx(382 - 120)
    body = json.loads(route.calls.last.request.content)
    assert body["model"] == "test-model"
    assert body["response_format"]["type"] == "json_schema"
    assert body["response_format"]["json_schema"]["strict"] is True
    system = body["messages"][0]["content"]
    assert system.startswith("You are Atlas, Artem's delegate in this call.")
    assert "what the tartan finish" in system  # noisy-ASR hint
    assert "cannot promise dates" in system  # brief always in the system prompt
    assert "50 requests per second" in system  # seed docs
    assert "Dima: database" in system  # experts
    assert "what did Artem finish this week?" in body["messages"][1]["content"]
    assert route.calls.last.request.headers["authorization"] == "Bearer sk-test"


@respx.mock
async def test_low_confidence_calls_hook_and_names_expert(world):
    world["hook_return"] = "Dima"
    respx.post(OPENAI_URL).mock(
        return_value=completion(answer="Maybe in Q1.", confidence=0.3, topic="postgres")
    )
    await orchestrator.handle(MID, utt("Atlas, when do we migrate to Postgres 17?"))

    assert world["hook"] == [(MID, "when do we migrate to Postgres 17?", "postgres", "Misha")]
    assert world["said"] == ["I don't know, asking Dima now."]
    assert world["rows"][0]["in_reply_to"] is None


@respx.mock
async def test_hook_dict_sets_in_reply_to(world):
    world["hook_return"] = {"expert": "Dima", "escalation_id": "esc_01"}
    respx.post(OPENAI_URL).mock(
        return_value=completion(answer="", confidence=0.2, needs_expert=True, topic="infra")
    )
    await orchestrator.handle(MID, utt("Atlas, is the deploy green?"))
    assert world["said"] == ["I don't know, asking Dima now."]
    assert world["events"][0]["data"]["in_reply_to"] == "esc_01"


@respx.mock
async def test_hook_none_asks_the_team(world):
    respx.post(OPENAI_URL).mock(
        return_value=completion(answer="", confidence=0.1, needs_expert=True, topic="infra")
    )
    await orchestrator.handle(MID, utt("Atlas, is the deploy green?"))
    assert world["said"] == ["I don't know yet, I'll ask the team."]


@respx.mock
async def test_commitment_question_goes_to_owner(world):
    world["hook_return"] = "Artem"
    route = respx.post(OPENAI_URL).mock(
        return_value=completion(
            answer="I can't commit for Artem.",
            confidence=0.95,
            needs_expert=True,
            topic="owner",
        )
    )
    await orchestrator.handle(MID, utt("Atlas, can Artem ship auth caching by Friday?"))
    system = json.loads(route.calls.last.request.content)["messages"][0]["content"]
    assert "NEVER make commitments" in system
    assert world["hook"][0][2] == "owner"
    assert world["said"] == ["I don't know, asking Artem now."]


@respx.mock
async def test_notetaker_is_silent(world):
    world["mode"] = "notetaker"
    route = respx.post(OPENAI_URL).mock(return_value=completion())
    await orchestrator.handle(MID, utt("Atlas, what did Artem finish?"))
    assert not route.called
    assert world["said"] == [] and world["events"] == []


@respx.mock
async def test_ignored_while_speaking(world):
    world["speaking"] = True
    route = respx.post(OPENAI_URL).mock(return_value=completion())
    await orchestrator.handle(MID, utt("Atlas, what did Artem finish?"))
    assert not route.called
    assert world["said"] == []


@respx.mock
async def test_no_trigger_no_llm(world):
    route = respx.post(OPENAI_URL).mock(return_value=completion())
    await orchestrator.handle(MID, utt("Our API limit is 100 requests per second."))
    assert not route.called


@respx.mock
async def test_slow_llm_plays_filler_first(world, monkeypatch):
    monkeypatch.setattr(orchestrator, "FILLER_AFTER_S", 0.05)

    async def slow(request):
        await asyncio.sleep(0.2)
        return completion()

    respx.post(OPENAI_URL).mock(side_effect=slow)
    await orchestrator.handle(MID, utt("Atlas, what did Artem finish?"))
    assert world["said"] == ["<filler>", "Artem finished the Slack escalation flow."]


@respx.mock
async def test_fast_llm_no_filler(world):
    respx.post(OPENAI_URL).mock(return_value=completion())
    await orchestrator.handle(MID, utt("Atlas, what did Artem finish?"))
    assert world["fillers"] == 0


@respx.mock
async def test_second_trigger_dropped_while_busy(world, monkeypatch, caplog):
    monkeypatch.setattr(orchestrator, "FILLER_AFTER_S", 5.0)

    async def slow(request):
        await asyncio.sleep(0.1)
        return completion()

    route = respx.post(OPENAI_URL).mock(side_effect=slow)
    with caplog.at_level(logging.INFO, logger="app.orchestrator"):
        await asyncio.gather(
            orchestrator.handle(MID, utt("Atlas, first question?")),
            orchestrator.handle(MID, utt("Atlas, second question?")),
        )
    assert route.call_count == 1
    assert len(world["said"]) == 1
    assert "dropped" in caplog.text


@respx.mock
async def test_agent_said_event_shape(world):
    respx.post(OPENAI_URL).mock(return_value=completion())
    await orchestrator.handle(MID, utt("Atlas, what did Artem finish?", ts=380))

    mock = json.loads((ROOT / "mocks" / "ws_agent_said.json").read_text())
    [event] = world["events"]
    assert event.keys() == mock.keys()
    assert event["type"] == "agent_said" and event["meeting_id"] == MID
    assert event["data"].keys() == mock["data"].keys()
    assert event["data"]["id"] == "as_01"
    assert event["data"]["text"] == "Artem finished the Slack escalation flow."
    assert isinstance(event["data"]["ts"], int) and 380 <= event["data"]["ts"] <= 382
    assert event["data"]["in_reply_to"] is None
    assert world["rows"][0]["text"] == event["data"]["text"]


async def test_no_openai_key_stays_silent(world, monkeypatch, caplog):
    monkeypatch.setenv("OPENAI_API_KEY", "")
    get_settings.cache_clear()
    with respx.mock:  # any real request would fail as unmocked
        with caplog.at_level(logging.WARNING, logger="app.orchestrator"):
            await orchestrator.handle(MID, utt("Atlas, what did Artem finish?"))
    assert world["said"] == [] and world["events"] == []
    assert "not configured" in caplog.text


@respx.mock
async def test_llm_http_error_never_raises(world):
    respx.post(OPENAI_URL).mock(return_value=httpx.Response(500, json={"error": {}}))
    await orchestrator.handle(MID, utt("Atlas, what did Artem finish?"))
    assert world["said"] == []


async def test_db_error_never_raises(world, monkeypatch):
    async def boom(meeting_id):
        raise RuntimeError("DATABASE_URL is not set")

    monkeypatch.setattr(db, "get_meeting_mode", boom)
    await orchestrator.handle(MID, utt("Atlas, what did Artem finish?"))
    assert world["said"] == []
    assert MID not in orchestrator._busy


@respx.mock
async def test_webhook_hook_wires_to_orchestrator(world):
    respx.post(OPENAI_URL).mock(return_value=completion())
    await webhooks_recall.orchestrator_hook(MID, utt("Atlas, what did Artem finish?"))
    assert world["said"] == ["Artem finished the Slack escalation flow."]


async def test_factcheck_skips_trigger(monkeypatch):
    from app import factcheck

    calls = []

    async def chat_json(*a, **k):
        calls.append(a)
        return {}

    monkeypatch.setattr(llm, "chat_json", chat_json)
    monkeypatch.setattr(factcheck.llm, "chat_json", chat_json)
    await factcheck._check(MID, utt("Okay so Atlas, what is our API limit of 50?"))
    assert calls == []


@respx.mock
async def test_mid_segment_trigger_reaches_llm_with_remainder(world):
    route = respx.post(OPENAI_URL).mock(return_value=completion())
    await orchestrator.handle(MID, utt("Right. Atlas, what are them did this week"))
    assert world["said"] == ["Artem finished the Slack escalation flow."]
    user = json.loads(route.calls.last.request.content)["messages"][1]["content"]
    assert user.endswith("Misha asks you: what are them did this week")


async def test_ask_keeps_guards_without_wake_word(world):
    world["speaking"] = True
    assert await orchestrator.ask(MID, utt("what the tartan finish"), "what") is False
    world["speaking"] = False
    world["mode"] = "notetaker"
    assert await orchestrator.ask(MID, utt("what the tartan finish"), "what") is False
    orchestrator._busy.add(MID)
    world["mode"] = "delegate"
    assert await orchestrator.ask(MID, utt("x"), "x") is False
    assert world["said"] == []


@pytest.fixture
def clock(monkeypatch):
    t = [1000.0]
    monkeypatch.setattr(orchestrator, "_now", lambda: t[0])
    return t


@respx.mock
async def test_armed_alias_then_question_within_window(world, clock, caplog):
    route = respx.post(OPENAI_URL).mock(return_value=completion())
    with caplog.at_level(logging.INFO, logger="app.orchestrator"):
        await orchestrator.handle(MID, utt("Okay Atlas."))
        assert route.call_count == 0
        assert "armed m_01 Misha" in caplog.text
        clock[0] += 5.0
        await orchestrator.handle(MID, utt("what did Artem finish this week?"))
    assert "armed → question in m_01: 'what did Artem finish this week?'" in caplog.text
    assert world["said"] == ["Artem finished the Slack escalation flow."]
    user = json.loads(route.calls.last.request.content)["messages"][1]["content"]
    assert user.endswith("Misha asks you: what did Artem finish this week?")
    assert orchestrator._armed == {}  # disarmed after use
    await orchestrator.handle(MID, utt("and what about next week?"))
    assert route.call_count == 1


@respx.mock
async def test_armed_expires_after_window(world, clock):
    route = respx.post(OPENAI_URL).mock(return_value=completion())
    await orchestrator.handle(MID, utt("Hey Atlas"))
    clock[0] += orchestrator.ARMED_S + 0.1
    await orchestrator.handle(MID, utt("what did Artem finish this week?"))
    assert route.call_count == 0
    assert world["said"] == []
    assert orchestrator._armed == {}


@respx.mock
async def test_armed_ignores_other_speaker_and_stays_armed(world, clock):
    route = respx.post(OPENAI_URL).mock(return_value=completion())
    await orchestrator.handle(MID, utt("Atlas.", speaker="Misha"))
    clock[0] += 1.0
    await orchestrator.handle(MID, utt("what did Artem finish this week?", speaker="Dima"))
    assert route.call_count == 0
    assert (MID, "Misha") in orchestrator._armed
    clock[0] += 1.0
    await orchestrator.handle(MID, utt("um", speaker="Misha"))  # too short: stays armed
    assert (MID, "Misha") in orchestrator._armed
    await orchestrator.handle(MID, utt("what did Artem finish?", speaker="Misha"))
    assert route.call_count == 1


async def test_armed_question_keeps_guards(world, clock):
    world["mode"] = "notetaker"
    await orchestrator.handle(MID, utt("Okay Atlas."))
    await orchestrator.handle(MID, utt("what did Artem finish?"))
    assert world["said"] == []

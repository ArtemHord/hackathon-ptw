"""M2.5b: orb signals (thinking / idle / ask / ask_done) sent to the agent page.

Reuses the in-memory world of test_escalation; agent_voice send_* are patched and recorded.
"""

import asyncio

import httpx
import pytest
import respx

from app import agent_voice, escalation, orchestrator, speech
from tests.test_escalation import (  # noqa: F401  (fixtures)
    DM,
    MID,
    OPENAI_URL,
    QUESTION,
    THREAD,
    completion,
    env,
    settle,
    start,
    world,
)

UTT = {"id": "u4", "speaker": "Julian", "text": f"Crew, {QUESTION}", "ts": 340}


@pytest.fixture
def calls(monkeypatch, world):  # noqa: F811
    log: list[tuple] = []

    async def state(mid, s):
        log.append(("state", mid, s))
        return True

    async def ask(mid, esc_id, question, expert, timeout_s):
        log.append(("ask", mid, esc_id, question, expert, timeout_s))
        return True

    async def ask_done(mid, esc_id, result):
        log.append(("ask_done", mid, esc_id, result))
        return True

    monkeypatch.setattr(agent_voice, "send_state", state)
    monkeypatch.setattr(agent_voice, "send_ask", ask)
    monkeypatch.setattr(agent_voice, "send_ask_done", ask_done)
    real_say = speech.say

    async def say(mid, text):
        log.append(("say", text))
        return await real_say(mid, text)

    monkeypatch.setattr(speech, "say", say)
    return log


@respx.mock
async def test_trigger_sends_thinking(world, calls):  # noqa: F811
    respx.post(OPENAI_URL).mock(
        return_value=completion("Yes.", confidence=0.95, needs_expert=False, topic="")
    )
    await orchestrator.handle(MID, UTT)
    assert calls[0] == ("state", MID, "thinking")
    assert ("state", MID, "idle") not in calls


async def test_notetaker_sends_nothing(world, calls):  # noqa: F811
    world["meeting"]["mode"] = "notetaker"
    await orchestrator.handle(MID, UTT)
    assert calls == []


@respx.mock
async def test_llm_failure_sends_idle(world, calls):  # noqa: F811
    respx.post(OPENAI_URL).mock(return_value=httpx.Response(500, json={"error": {}}))
    await orchestrator.handle(MID, UTT)
    assert calls == [("state", MID, "thinking"), ("state", MID, "idle")]


async def test_escalation_start_sends_ask(world, calls):  # noqa: F811
    await start(world)
    assert calls == [("ask", MID, "esc_01", QUESTION, "Dima", escalation.ESCALATION_TIMEOUT_S)]


async def test_answered_ask_done_before_say(world, calls):  # noqa: F811
    await start(world)
    await escalation.on_expert_reply(DM, THREAD, "Thursday", "U_DIMA")
    await settle()
    tail = calls[1:]
    assert tail[0] == ("ask_done", MID, "esc_01", "answered")
    assert tail[1] == ("say", "Dima says: Thursday")


async def test_timeout_sends_ask_done_timeout(world, calls, monkeypatch):  # noqa: F811
    monkeypatch.setattr(escalation, "ESCALATION_TIMEOUT_S", 0.05)
    await start(world)
    await asyncio.sleep(0.3)
    assert ("ask_done", MID, "esc_01", "timeout") in calls
    assert calls.index(("ask_done", MID, "esc_01", "timeout")) < calls.index(
        ("say", "Dima hasn't answered yet — I've added it to follow-ups.")
    )


async def test_late_reply_sends_no_ask_done(world, calls, monkeypatch):  # noqa: F811
    monkeypatch.setattr(escalation, "ESCALATION_TIMEOUT_S", 0.05)
    await start(world)
    await asyncio.sleep(0.3)
    calls.clear()
    await escalation.on_expert_reply(DM, THREAD, "Thursday", "U_DIMA")
    await settle()
    assert [c for c in calls if c[0] == "ask_done"] == []


async def test_slow_orb_does_not_break_voice(world, calls, monkeypatch):  # noqa: F811
    async def boom(*a, **k):
        raise RuntimeError("page gone")

    monkeypatch.setattr(agent_voice, "send_ask_done", boom)
    await start(world)
    await escalation.on_expert_reply(DM, THREAD, "Thursday", "U_DIMA")
    await settle()
    assert world["said"] == ["Dima says: Thursday"]

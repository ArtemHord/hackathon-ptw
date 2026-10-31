"""The "Crew, ..." trigger (SPEC "Głos: ElevenLabs w rozmowie", steps 2-6).

utterance -> alias at the start? -> delegate mode, not speaking, not busy -> context
(last 120 s, brief, seed docs, experts) -> LLM JSON {answer, confidence, needs_expert,
topic} -> filler if slow -> say() -> agent_said row + WS event.
"""

import asyncio
import json
import logging
import re
import time
from pathlib import Path
from typing import Any

from app import agent_voice, db, escalation, hub, llm, speech

log = logging.getLogger(__name__)

FILLER_AFTER_S = 1.5
CONTEXT_WINDOW_S = 120.0
MIN_CONFIDENCE = 0.6
SEED_DIR = Path(__file__).resolve().parent.parent / "seed"

# Longest first so "call crew" wins over "crew", "crue" over "cru".
_ALIAS = r"(?:call[\s,]+crew|hey[\s,]+crew|crew|crue|cru|kru)"
_TRIGGER = re.compile(rf"^[\W_]*{_ALIAS}(?![\w'])[\W_]*(.*)$", re.IGNORECASE | re.DOTALL)

ANSWER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "answer": {"type": "string"},
        "confidence": {"type": "number"},
        "needs_expert": {"type": "boolean"},
        "topic": {"type": "string"},
    },
    "required": ["answer", "confidence", "needs_expert", "topic"],
    "additionalProperties": False,
}

SYSTEM_PROMPT = """You are Crew, an AI delegate attending this meeting for its owner.
People in the call address you as "Crew". Your words are spoken aloud in the call.

Rules:
- Answer ONLY from the context below: the owner's brief, the company documents and the \
recent transcript. Never guess or invent facts.
- At most 2 short spoken sentences, in English. No markdown, no lists.
- NEVER make commitments, promises, estimates or deadlines on behalf of the owner. For any \
question asking you to commit, agree, promise or give a date for the owner, set \
needs_expert=true and topic="owner".
- If the context does not contain the answer, set needs_expert=true and topic to the best \
matching expert topic from the list below (or "owner" if none fits).
- confidence: 0-1, how sure you are the answer is fully supported by the context.
- topic: "" when needs_expert is false.

## Owner's brief
{brief}

## Experts (name: topics)
{experts}

## Company documents
{docs}
"""

_docs_cache: str | None = None
_experts_cache: str | None = None
_busy: set[str] = set()  # meeting_ids with an answer in progress


async def on_needs_expert(
    meeting_id: str, question: str, topic: str, asked_by: str
) -> str | dict[str, Any] | None:
    """Escalation hook (M3.3): escalation.start. Returns None, an expert name, or
    {"expert": name, "escalation_id": id}."""
    return await escalation.start(meeting_id, question, topic, asked_by)


def parse_trigger(text: str) -> str | None:
    """The question after a leading "Crew" alias, or None (no alias / nothing asked)."""
    m = _TRIGGER.match(text or "")
    if not m:
        return None
    question = m.group(1).strip()
    return question or None


def seed_docs() -> str:
    """HACK: all seed/*.md straight into the prompt until RAG (M4.1). Read once."""
    global _docs_cache
    if _docs_cache is None:
        parts = [f"### {p.name}\n{p.read_text().strip()}" for p in sorted(SEED_DIR.glob("*.md"))]
        _docs_cache = "\n\n".join(parts)
    return _docs_cache


def experts_text() -> str:
    global _experts_cache
    if _experts_cache is None:
        try:
            data = json.loads((SEED_DIR / "experts.json").read_text())
            lines = [
                f"- {e['name']}: {', '.join(e.get('topics') or [])}"
                for e in data.get("experts", [])
            ]
        except (OSError, ValueError, KeyError, TypeError) as e:
            log.warning("experts.json unreadable: %s", e)
            lines = []
        _experts_cache = "\n".join(lines) or "(none)"
    return _experts_cache


def build_messages(
    brief: str, recent: list[dict[str, Any]], speaker: str, question: str
) -> list[dict[str, str]]:
    system = SYSTEM_PROMPT.format(
        brief=brief.strip() or "(no brief)", experts=experts_text(), docs=seed_docs()
    )
    transcript = "\n".join(f"{u['speaker']}: {u['text']}" for u in recent) or "(empty)"
    user = f"Recent transcript (last 2 minutes):\n{transcript}\n\n{speaker} asks you: {question}"
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def _normalize(raw: dict[str, Any]) -> dict[str, Any]:
    try:
        confidence = min(1.0, max(0.0, float(raw.get("confidence") or 0.0)))
    except (TypeError, ValueError):
        confidence = 0.0
    return {
        "answer": str(raw.get("answer") or "").strip(),
        "confidence": confidence,
        "needs_expert": bool(raw.get("needs_expert")),
        "topic": str(raw.get("topic") or "").strip(),
    }


def _ms(a: float, b: float) -> int:
    return int((b - a) * 1000)


async def _safe(coro, default):
    try:
        return await coro
    except Exception as e:
        log.warning("orchestrator context fetch failed: %s", e)
        return default


async def handle(meeting_id: str, utterance: dict[str, Any]) -> None:
    """Entry point from the transcript webhook task. Never raises."""
    try:
        question = parse_trigger(str(utterance.get("text") or ""))
        if question is None:
            return
        if agent_voice.is_speaking(meeting_id):
            log.info("crew trigger ignored (agent speaking) in %s", meeting_id)
            return
        if meeting_id in _busy:
            log.info("crew trigger dropped (answer in progress) in %s: %r", meeting_id, question)
            return
        _busy.add(meeting_id)
        try:
            await _answer(meeting_id, utterance, question)
        finally:
            _busy.discard(meeting_id)
    except Exception:
        log.exception("orchestrator failed for meeting %s", meeting_id)


async def _answer(meeting_id: str, utterance: dict[str, Any], question: str) -> None:
    t0 = time.monotonic()
    if await db.get_meeting_mode(meeting_id) != "delegate":
        return  # notetaker: listen only
    asked_by = str(utterance.get("speaker") or "Someone")
    call_ts = float(utterance.get("ts") or 0.0)

    brief, recent = await asyncio.gather(
        _safe(db.get_brief(meeting_id), ""),
        _safe(db.get_recent_utterances(meeting_id, call_ts - CONTEXT_WINDOW_S), []),
    )
    messages = build_messages(brief, recent, asked_by, question)
    task = asyncio.create_task(llm.chat_json(messages, "crew_answer", ANSWER_SCHEMA))

    filler = False
    wait_s = max(0.0, FILLER_AFTER_S - (time.monotonic() - t0))
    done, _ = await asyncio.wait({task}, timeout=wait_s)
    if not done:
        filler = True
        await speech.say_filler(meeting_id)
    try:
        result = _normalize(await task)
    except Exception as e:
        log.warning("crew LLM failed in %s, staying silent: %s", meeting_id, e)
        return
    t_llm = time.monotonic()

    escalation_id: str | None = None
    if result["needs_expert"] or result["confidence"] < MIN_CONFIDENCE or not result["answer"]:
        expert: str | None = None
        try:
            hooked = await on_needs_expert(
                meeting_id, question, result["topic"] or "owner", asked_by
            )
        except Exception:
            log.exception("on_needs_expert failed in %s", meeting_id)
            hooked = None
        if isinstance(hooked, dict):
            expert = hooked.get("expert") or None
            escalation_id = hooked.get("escalation_id") or None
        elif isinstance(hooked, str) and hooked.strip():
            expert = hooked.strip()
        text = (
            f"I don't know, asking {expert} now."
            if expert
            else ("I don't know yet, I'll ask the team.")
        )
    else:
        text = result["answer"]

    delivered = await speech.say(meeting_id, text)
    t_played = time.monotonic()
    log.info(
        "crew latency %s: trigger->llm %dms, llm->tts+push %dms, total %dms (filler=%s, "
        "delivered=%s, conf=%.2f, needs_expert=%s, topic=%r)",
        meeting_id,
        _ms(t0, t_llm),
        _ms(t_llm, t_played),
        _ms(t0, t_played),
        filler,
        delivered,
        result["confidence"],
        result["needs_expert"],
        result["topic"],
    )

    ts = int(round(call_ts + (t_played - t0)))
    row = await db.insert_agent_said(meeting_id, text, float(ts), escalation_id)
    await hub.publish(
        meeting_id,
        "agent_said",
        {"id": row["id"], "text": text, "ts": ts, "in_reply_to": escalation_id},
    )

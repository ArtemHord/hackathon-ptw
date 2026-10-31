"""The "Atlas, ..." trigger (SPEC "Głos: ElevenLabs w rozmowie", steps 2-6).

utterance -> wake word in the first 6 words + 2-word question? -> delegate mode, not
speaking, not busy -> context (last 120 s, brief, seed docs, experts) -> LLM JSON {answer,
confidence, needs_expert, topic} -> filler if slow -> say() -> agent_said row + WS event.
"""

import asyncio
import logging
import re
import time
from functools import lru_cache
from pathlib import Path
from typing import Any

from app import agent_voice, db, escalation, hub, llm, runtime, speech

log = logging.getLogger(__name__)

FILLER_AFTER_S = 1.5
CONTEXT_WINDOW_S = 120.0
MIN_CONFIDENCE = 0.6
SEED_DIR = Path(__file__).resolve().parent.parent / "seed"

# Wake word (M6.3): AGENT_NAME ("Atlas") as a whole word within the first WAKE_MAX_WORDS
# words (Recall merges sentences: "blah. Atlas, what..."), then at least 2 words of question.
WAKE_MAX_WORDS = 6
MIN_QUESTION_WORDS = 2
# HACK: ASR spellings of "Atlas" heard in tests; extras for other names go here.
_ALIAS_EXTRA = {"atlas": ("atlass", "atlis")}
_SEGMENT_START_ALIAS = {"atlas": ("at last",)}  # too common mid-sentence: only as first words
_WORD = re.compile(r"[a-z0-9]+(?:'[a-z]+)?", re.IGNORECASE)
_SHORT = "question shorter than"
# "Armed" wake word (M6.6): "Okay Atlas." alone arms (meeting, speaker) for ARMED_S; that
# speaker's next utterance with >= MIN_QUESTION_WORDS words is the question.
ARMED_S = 6.0
_armed: dict[tuple[str, str], float] = {}  # (meeting_id, speaker) -> monotonic deadline


def _now() -> float:
    return time.monotonic()


def wake_aliases(name: str | None = None) -> tuple[str, ...]:
    """Every alias, the one place they are built: name, hey/okay/ok name, ASR spellings."""
    n = (name or runtime.get("AGENT_NAME")).strip().lower()
    return (f"hey {n}", f"okay {n}", f"ok {n}", n, *_ALIAS_EXTRA.get(n, ()))


@lru_cache
def _wake_res(name: str) -> tuple[re.Pattern[str], re.Pattern[str] | None]:
    def alt(aliases) -> str:
        parts = sorted(aliases, key=len, reverse=True)  # "hey atlas" wins over "atlas"
        return "|".join(r"[\s,]+".join(map(re.escape, a.split())) for a in parts)

    anywhere = re.compile(rf"(?<![\w'])(?:{alt(wake_aliases(name))})(?![\w'])", re.IGNORECASE)
    start_only = _SEGMENT_START_ALIAS.get(name.strip().lower())
    start = (
        re.compile(rf"^[\W_]*(?:{alt(start_only)})(?![\w'])", re.IGNORECASE) if start_only else None
    )
    return anywhere, start


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

# Owner and agent names come from runtime settings (web UI, env fallback).
SYSTEM_PROMPT = """You are {agent}, {owner}'s delegate in this call.
People in the call address you as "{agent}". Your words are spoken aloud in the call.

Rules:
- The question comes from noisy live speech recognition: interpret it charitably using the \
brief and the documents ("what the tartan finish" = "what did {owner} finish"). If it is \
still unclear what was asked, reply with ONE short clarifying question.
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


def match_trigger(text: str) -> tuple[str | None, str]:
    """(question, reason). Question is the text after the wake word, or None + why not."""
    text = (text or "").replace("\u2019", "'")
    anywhere, start = _wake_res(runtime.get("AGENT_NAME").strip().lower())
    m = start.match(text) if start else None
    if m is None:
        m = anywhere.search(text)
        if m is None:
            return None, "no wake word"
        before = len(_WORD.findall(text[: m.start()]))
        if before >= WAKE_MAX_WORDS:
            return None, f"wake word is word {before + 1}, after the first {WAKE_MAX_WORDS}"
    question = re.sub(r"^[\W_]+", "", text[m.end() :]).strip()
    if len(_WORD.findall(question)) < MIN_QUESTION_WORDS:
        return None, f"{_SHORT} {MIN_QUESTION_WORDS} words: {question!r}"
    return question, "trigger"


def parse_trigger(text: str) -> str | None:
    """The question after the wake word, or None (no wake word / too short). Pure."""
    return match_trigger(text)[0]


def seed_docs() -> str:
    """HACK: all seed/*.md straight into the prompt until RAG (M4.1). Read once."""
    global _docs_cache
    if _docs_cache is None:
        parts = [f"### {p.name}\n{p.read_text().strip()}" for p in sorted(SEED_DIR.glob("*.md"))]
        _docs_cache = "\n\n".join(parts)
    return _docs_cache


async def experts_text() -> str:
    """Expert list for the prompt, from escalation.load_experts() (DB when configured, seed
    file otherwise). Cached; experts CRUD (settings_api) resets _experts_cache."""
    global _experts_cache
    if _experts_cache is None:
        experts = await escalation.load_experts()
        lines = [f"- {e.name}: {', '.join(e.topics or [])}" for e in experts]
        _experts_cache = "\n".join(lines) or "(none)"
    return _experts_cache


def build_messages(
    brief: str,
    recent: list[dict[str, Any]],
    speaker: str,
    question: str,
    experts: str = "(none)",
) -> list[dict[str, str]]:
    system = SYSTEM_PROMPT.format(
        agent=runtime.get("AGENT_NAME"),
        owner=runtime.get("OWNER_NAME"),
        brief=brief.strip() or "(no brief)",
        experts=experts,
        docs=seed_docs(),
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
    text = str(utterance.get("text") or "")
    log.info("utterance %s %s: %s", meeting_id, utterance.get("speaker"), text[:80])
    key = (meeting_id, str(utterance.get("speaker") or ""))
    question, reason = match_trigger(text)
    if question is None and reason.startswith(_SHORT):
        _armed[key] = _now() + ARMED_S
        log.info("armed %s %s for %.0fs: %s", meeting_id, key[1], ARMED_S, reason)
        return
    if question is None:
        question = _armed_question(key, text)
        if question is None:
            log.info("no trigger in %s: %s", meeting_id, reason)
            return
        log.info("armed → question in %s: %r", meeting_id, question)
    else:
        _armed.pop(key, None)
        log.info("trigger in %s: %r", meeting_id, question)
    await ask(meeting_id, utterance, question)


def _armed_question(key: tuple[str, str], text: str) -> str | None:
    """The whole utterance as the question if this speaker is armed and it has 2+ words.
    Disarms on use or expiry; a too-short utterance keeps the window open."""
    deadline = _armed.get(key)
    if deadline is None:
        return None
    if _now() > deadline:
        _armed.pop(key, None)
        log.info("armed expired %s %s", *key)
        return None
    question = re.sub(r"^[\W_]+", "", text).strip()
    if len(_WORD.findall(question)) < MIN_QUESTION_WORDS:
        return None
    _armed.pop(key, None)
    return question


def is_busy(meeting_id: str) -> bool:
    """An answer is in progress or the agent is speaking (POST /meetings/{id}/ask -> 409)."""
    return meeting_id in _busy or agent_voice.is_speaking(meeting_id)


async def manual_question(meeting_id: str, text: str | None) -> tuple[dict[str, Any], str] | None:
    """(utterance, question) for a button trigger (POST /meetings/{id}/ask, /debug/ask): the
    given text, or the latest human utterance. None if there is nothing to answer."""
    from app.webhooks_recall import is_bot_speaker  # lazy: webhooks_recall -> orchestrator

    last = [
        u
        for u in await db.get_last_utterances(meeting_id, 10)
        if not is_bot_speaker(str(u.get("speaker") or ""))
    ]
    latest = last[-1] if last else None
    text = (text or "").strip()
    if not text:
        if latest is None:
            return None
        text = str(latest.get("text") or "").strip()
    question = parse_trigger(text) or text
    utterance = {
        "id": latest.get("id") if latest else None,
        "speaker": (latest or {}).get("speaker") or "Someone",
        "text": text,
        "ts": int(float((latest or {}).get("ts_start") or 0.0)),
    }
    return utterance, question


async def ask(meeting_id: str, utterance: dict[str, Any], question: str) -> bool:
    """Answer flow without the wake-word check (also POST /debug/ask). Keeps the speaking,
    busy and delegate-mode guards. False if dropped by a guard or failed. Never raises."""
    try:
        if agent_voice.is_speaking(meeting_id):
            log.info("trigger ignored (agent speaking) in %s", meeting_id)
            return False
        if meeting_id in _busy:
            log.info("trigger dropped (answer in progress) in %s: %r", meeting_id, question)
            return False
        _busy.add(meeting_id)
        try:
            return await _answer(meeting_id, utterance, question)
        finally:
            _busy.discard(meeting_id)
    except Exception:
        log.exception("orchestrator failed for meeting %s", meeting_id)
        return False


async def _orb(coro) -> None:
    """Orb visuals are best effort: bounded, never raises, never blocks the voice path."""
    try:
        await asyncio.wait_for(coro, 0.3)
    except Exception as e:
        log.info("orb signal failed: %s", e.__class__.__name__)


async def _answer(meeting_id: str, utterance: dict[str, Any], question: str) -> bool:
    t0 = time.monotonic()
    if await db.get_meeting_mode(meeting_id) != "delegate":
        return False  # notetaker: listen only
    await _orb(agent_voice.send_state(meeting_id, "thinking"))
    asked_by = str(utterance.get("speaker") or "Someone")
    call_ts = float(utterance.get("ts") or 0.0)

    brief, recent, experts = await asyncio.gather(
        _safe(db.get_brief(meeting_id), ""),
        _safe(db.get_recent_utterances(meeting_id, call_ts - CONTEXT_WINDOW_S), []),
        _safe(experts_text(), "(none)"),
    )
    messages = build_messages(brief, recent, asked_by, question, experts)
    task = asyncio.create_task(llm.chat_json(messages, "agent_answer", ANSWER_SCHEMA))

    filler = False
    wait_s = max(0.0, FILLER_AFTER_S - (time.monotonic() - t0))
    done, _ = await asyncio.wait({task}, timeout=wait_s)
    if not done:
        filler = True
        await speech.say_filler(meeting_id)
    try:
        result = _normalize(await task)
    except Exception as e:
        log.warning("agent LLM failed in %s, staying silent: %s", meeting_id, e)
        await _orb(agent_voice.send_state(meeting_id, "idle"))
        return False
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
        "agent latency %s: trigger->llm %dms, llm->tts+push %dms, total %dms (filler=%s, "
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
    return True

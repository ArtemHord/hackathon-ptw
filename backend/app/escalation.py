"""Slack escalation loop (SPEC "Eskalacja na Slacku", Przepływ 1-7).

start(): match expert -> escalations row (waiting) -> `escalation_created` -> background
DM via Notifier + timeout task; returns at once so the agent says "asking Dima now".
on_expert_reply(): thread reply -> first answer wins -> "Dima says: ..." in the call
(voice + Recall chat), agent_said + fact -> `escalation_answered` -> thread note.
Timeout (ESCALATION_TIMEOUT_S): spoken follow-up line + action item + `escalation_answered`
with status timeout. A late reply is still stored and published, never spoken.
"""

import asyncio
import json
import logging
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app import db, hub, recall, speech
from app.config import get_settings
from app.notifier.base import Expert, SentMessage, get_notifier

log = logging.getLogger(__name__)

SEED_PATH = Path(__file__).resolve().parent.parent / "seed" / "experts.json"
_cache: list[Expert] | None = None

ESCALATION_TIMEOUT_S = 120.0
CONTEXT_LINES = 3
LIVE_STATUSES = {"in_call", "joining"}
THANKS_LIVE = "Thanks — passed it on in the call."
THANKS_ENDED = "The call has ended — I've added it to the summary."
THANKS_LATE = "Thanks — the call moved on, I've added it to the summary."

_tasks: set[asyncio.Task] = set()
_timeouts: dict[str, asyncio.Task] = {}


def _tokens(s: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", s.lower()))


def match_expert(topic: str, experts: list[Expert]) -> Expert:
    """Best expert by token/substring overlap of topic vs expert topics; owner as fallback."""
    owner = next((e for e in experts if e.is_owner), None) or experts[0]
    topic_l = (topic or "").lower().strip()
    if not topic_l or topic_l == "owner":
        return owner
    t_tokens = _tokens(topic_l)
    best, best_score = owner, 0
    for e in experts:
        if e.is_owner:
            continue
        score = 0
        for t in e.topics:
            t = t.lower().strip()
            if not t:
                continue
            if t == topic_l:
                score += 3
            elif t in topic_l or topic_l in t:
                score += 2
            elif _tokens(t) & t_tokens:
                score += 1
        if score > best_score:
            best, best_score = e, score
    return best


def _seed_experts() -> list[Expert]:
    data = json.loads(SEED_PATH.read_text())["experts"]
    return [
        Expert(**{**d, "is_owner": "owner" in d.get("topics", []) or d.get("is_owner", False)})
        for d in data
    ]


async def load_experts(refresh: bool = False) -> list[Expert]:
    """Cached experts from DB; HACK: falls back to seed file when no DATABASE_URL."""
    global _cache
    if _cache is not None and not refresh:
        return _cache
    if get_settings().DATABASE_URL:
        _cache = [Expert(**r) for r in await db.list_experts()]
    if not _cache:
        _cache = _seed_experts()
    return _cache


async def seed_experts() -> None:
    """HACK: upsert seed/experts.json at startup, only when DATABASE_URL is set."""
    if not get_settings().DATABASE_URL:
        return
    try:
        await db.upsert_experts(json.loads(SEED_PATH.read_text())["experts"])
        await load_experts(refresh=True)
    except Exception as e:
        log.warning("expert seed failed: %s", e)


def _notifier_for(channel: str):
    """HACK: without SLACK_BOT_TOKEN, slack experts go to the fake notifier (offline demo/tests)."""
    if channel == "slack" and not get_settings().SLACK_BOT_TOKEN:
        from app.notifier import fake  # noqa: F401  registers "fake"

        return get_notifier("fake")
    return get_notifier(channel)


def _spawn(coro) -> asyncio.Task:
    task = asyncio.create_task(coro)
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    return task


async def _try(coro, what: str, default: Any = None) -> Any:
    try:
        return await coro
    except Exception as e:
        log.warning("escalation: %s failed: %s", what, e)
        return default


def _int(v: Any) -> int | None:
    return None if v is None else int(round(float(v)))


def public(row: dict[str, Any], expert: str | None = None) -> dict[str, Any]:
    """The escalation object of docs/API.pl.md (WS events and GET /meetings/{id})."""
    return {
        "id": row["id"],
        "expert": row.get("expert") or expert or "the expert",
        "channel": row.get("channel") or "slack",
        "question": row["question"],
        "asked_by": row.get("asked_by"),
        "ts": _int(row.get("ts")) or 0,
        "status": row["status"],
        "answer": row.get("answer"),
        "answered_ts": _int(row.get("answered_ts")),
    }


def _elapsed_s(since: datetime | None) -> float:
    if since is None:
        return 0.0
    if since.tzinfo is None:
        since = since.replace(tzinfo=UTC)
    return max(0.0, (datetime.now(UTC) - since).total_seconds())


async def start(meeting_id: str, question: str, topic: str, asked_by: str) -> dict[str, Any] | None:
    """Orchestrator hook. Returns {"expert", "escalation_id"} before any Slack I/O; None if the
    escalation could not be recorded. Never raises."""
    try:
        expert = match_expert(topic, await load_experts())
        meeting, recent = await asyncio.gather(
            _try(db.get_meeting(meeting_id), "get_meeting"),
            _try(db.get_last_utterances(meeting_id, CONTEXT_LINES), "get_last_utterances", []),
        )
        meeting = meeting or {}
        # Same clock as the transcript: the question utterance was stored just before us.
        ts = float(recent[-1]["ts_start"]) if recent else _elapsed_s(meeting.get("started_at"))
        row = await db.insert_escalation(
            meeting_id=meeting_id,
            expert_id=expert.id,
            channel=expert.channel,
            question=question,
            asked_by=asked_by,
            ts=ts,
        )
    except Exception:
        log.exception("escalation start failed in %s", meeting_id)
        return None
    esc_id = row["id"]
    await _try(
        hub.publish(meeting_id, "escalation_created", public(row, expert.name)), "publish created"
    )
    context = [f"{u['speaker']}: {u['text']}" for u in recent][-CONTEXT_LINES:]
    _spawn(_deliver(esc_id, expert, meeting.get("title") or "", asked_by, question, context))
    _timeouts[esc_id] = _spawn(_timeout(meeting_id, esc_id, expert.name, question))
    log.info("escalation %s: %r -> %s (%s)", esc_id, question, expert.name, expert.channel)
    return {"expert": expert.name, "escalation_id": esc_id}


async def _deliver(
    esc_id: str,
    expert: Expert,
    meeting_title: str,
    asked_by: str,
    question: str,
    context: list[str],
) -> None:
    """DM the expert and remember the thread. On failure the escalation stays waiting."""
    try:
        notifier = _notifier_for(expert.channel)
        if notifier is None:
            log.warning("escalation %s: no notifier for channel %r", esc_id, expert.channel)
            return
        sent = await notifier.send_question(
            expert,
            meeting_title=meeting_title or "Call",
            asked_by=asked_by,
            question=question,
            context_lines=context,
        )
        await db.set_escalation_external(esc_id, sent.external_msg_id, sent.external_channel_id)
    except Exception as e:
        log.warning("escalation %s: notifying %s failed: %s", esc_id, expert.name, e)


async def _speak(meeting_id: str, text: str, esc_id: str, ts: float, chat: bool, bot_id) -> None:
    """Voice + (optional) Recall chat + agent_said row/event. Each step best effort."""
    await _try(speech.say(meeting_id, text), "say")
    if chat:
        await _try(recall.send_chat_message(bot_id, text), "recall chat")
    said = await _try(db.insert_agent_said(meeting_id, text, ts, esc_id), "insert agent_said")
    if said:
        await _try(
            hub.publish(
                meeting_id,
                "agent_said",
                {"id": said["id"], "text": text, "ts": _int(ts), "in_reply_to": esc_id},
            ),
            "publish agent_said",
        )


async def _timeout(meeting_id: str, esc_id: str, expert: str, question: str) -> None:
    try:
        await asyncio.sleep(ESCALATION_TIMEOUT_S)
        row = await db.timeout_escalation(esc_id)
        if row is None:
            return  # answered in time
        name = row.get("expert") or expert
        meeting = await _try(db.get_meeting(meeting_id), "get_meeting") or {}
        if meeting.get("status") in LIVE_STATUSES:
            ts = float(row.get("ts") or 0) + _elapsed_s(row.get("asked_at"))
            line = f"{name} hasn't answered yet — I've added it to follow-ups."
            await _speak(meeting_id, line, esc_id, ts, False, None)
        await _try(
            db.append_action_item(meeting_id, {"owner": name, "text": question, "due": None}),
            "append action item",
        )
        await _try(
            hub.publish(meeting_id, "escalation_answered", public(row, name)), "publish timeout"
        )
        log.info("escalation %s timed out (%s)", esc_id, name)
    except asyncio.CancelledError:
        pass
    except Exception:
        log.exception("escalation %s timeout handling failed", esc_id)
    finally:
        _timeouts.pop(esc_id, None)


async def on_expert_reply(channel_id: str, thread_ts: str, text: str, user_id: str) -> None:
    """Slack thread reply from an expert. Only the first reply counts. Never raises."""
    try:
        await _on_reply(channel_id, thread_ts, (text or "").strip(), user_id)
    except Exception:
        log.exception("expert reply handling failed (thread %s)", thread_ts)


async def _on_reply(channel_id: str, thread_ts: str, text: str, user_id: str) -> None:
    if not text:
        return
    esc = await db.get_escalation_by_external(thread_ts, channel_id)
    if esc is None:
        log.info("reply in unknown thread %s/%s ignored", channel_id, thread_ts)
        return
    if esc["status"] == "answered":
        log.info("escalation %s already answered, extra reply from %s ignored", esc["id"], user_id)
        return
    esc_id, meeting_id = esc["id"], esc["meeting_id"]
    answered_ts = float(esc.get("ts") or 0) + _elapsed_s(esc.get("asked_at"))
    row = await db.answer_escalation(esc_id, text, answered_ts)
    if row is None:
        return  # lost a race with another reply
    late = row.get("prev_status") == "timeout"
    if not late:
        task = _timeouts.pop(esc_id, None)
        if task is not None and task is not asyncio.current_task():
            task.cancel()
    expert = row.get("expert") or esc.get("expert") or "The expert"
    meeting = await _try(db.get_meeting(meeting_id), "get_meeting") or {}
    live = meeting.get("status") in LIVE_STATUSES
    if live and not late:
        line = f"{expert} says: {text}"
        await _speak(meeting_id, line, esc_id, answered_ts, True, meeting.get("recall_bot_id"))
        await _try(
            db.insert_fact(meeting_id, expert, f"Q: {row['question']}\nA: {text}", "answer"),
            "insert fact",
        )
    await _try(
        hub.publish(meeting_id, "escalation_answered", public(row, expert)), "publish answered"
    )
    notifier = _notifier_for(row.get("channel") or "slack")
    if notifier is not None:
        note = THANKS_LIVE if live and not late else (THANKS_LATE if live else THANKS_ENDED)
        sent = SentMessage(
            channel=row.get("channel") or "slack",
            external_msg_id=row.get("external_msg_id") or thread_ts,
            external_channel_id=row.get("external_channel_id") or channel_id,
        )
        await _try(notifier.post_reply(sent, note), "thread reply")
    log.info("escalation %s answered by %s (late=%s, live=%s)", esc_id, expert, late, live)

"""Post-call pipeline (M4.2): one LLM call -> summary, decisions, action items, facts.

Runs on bot.done (webhooks_recall.postcall_hook) and, as a fallback, 5 s after
POST /meetings/{id}/leave. Idempotent (per-meeting lock + "summary already set" guard).
Never raises: on failure it logs and publishes nothing.
"""

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any

from app import db, hub, llm, rag

log = logging.getLogger(__name__)

LEAVE_DELAY_S = 5.0
KINDS = ["decision", "number", "date", "owner"]

SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["summary", "decisions", "action_items", "facts"],
    "properties": {
        "summary": {"type": "string"},
        "decisions": {"type": "array", "items": {"type": "string"}},
        "action_items": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["owner", "text", "due"],
                "properties": {
                    "owner": {"type": "string"},
                    "text": {"type": "string"},
                    "due": {"type": ["string", "null"]},
                },
            },
        },
        "facts": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["speaker", "text", "kind"],
                "properties": {
                    "speaker": {"type": "string"},
                    "text": {"type": "string"},
                    "kind": {"type": "string", "enum": KINDS},
                },
            },
        },
    },
}

SYSTEM = (
    "You write the post-call notes of a meeting. Write in English. Use ONLY what is in the "
    "transcript, the brief and the expert answers below; never invent decisions, owners, "
    "numbers, dates or deadlines. summary: at most 3 sentences. decisions: short statements "
    "of what was decided. action_items: who must do what, due is a date/day phrase exactly as "
    "spoken or null. facts: concrete decisions, numbers, dates and owners stated by a "
    "speaker (kind: decision|number|date|owner). Expert answers received on Slack (even late "
    "ones) count as part of the call. Empty lists are fine."
)

_locks: dict[str, asyncio.Lock] = {}
_tasks: set[asyncio.Task] = set()


def _fmt_ts(sec: Any) -> str:
    s = int(float(sec or 0))
    return f"{s // 60:02d}:{s % 60:02d}"


def build_prompt(
    brief: str, utterances: list[dict[str, Any]], escalations: list[dict[str, Any]]
) -> str:
    lines = [f"[{_fmt_ts(u.get('ts_start'))}] {u['speaker']}: {u['text']}" for u in utterances]
    esc = []
    for e in escalations:
        who = e.get("expert") or "expert"
        if e.get("answer"):
            esc.append(f"- Question for {who}: {e['question']} -> {who} answered: {e['answer']}")
        else:
            esc.append(f"- Question for {who}: {e['question']} -> no answer ({e.get('status')})")
    return (
        f"BRIEF:\n{brief or '(none)'}\n\nTRANSCRIPT:\n{chr(10).join(lines) or '(empty)'}\n\n"
        f"SLACK ESCALATIONS:\n{chr(10).join(esc) or '(none)'}"
    )


def merge_action_items(
    existing: list[dict[str, Any]], new: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Existing (e.g. escalation timeouts) first, then LLM ones; dedupe by text, ignoring case."""
    out, seen = [], set()
    for it in [*(existing or []), *new]:
        if not isinstance(it, dict):
            continue
        key = " ".join(str(it.get("text", "")).split()).lower()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append({"owner": it.get("owner"), "text": it["text"], "due": it.get("due")})
    return out


def _duration_min(m: dict[str, Any]) -> int:
    start, end = m.get("started_at"), m.get("ended_at") or datetime.now(UTC)
    if not start:
        return 0
    try:
        return max(0, round((end - start).total_seconds() / 60))
    except TypeError:
        return 0


async def run(meeting_id: str) -> None:
    lock = _locks.setdefault(meeting_id, asyncio.Lock())
    async with lock:
        try:
            await _run(meeting_id)
        except Exception:
            log.exception("postcall failed for meeting %s", meeting_id)


async def _run(meeting_id: str) -> None:
    meeting = await db.get_meeting(meeting_id)
    if meeting is None:
        log.info("postcall: meeting %s not found", meeting_id)
        return
    if meeting.get("summary"):
        log.info("postcall: meeting %s already summarised, skipping", meeting_id)
        return
    utterances = await db.get_all_utterances(meeting_id)
    brief = await db.get_brief(meeting_id)
    escalations = await db.list_escalations(meeting_id)
    try:
        out = await llm.chat_json(
            [
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": build_prompt(brief, utterances, escalations)},
            ],
            "postcall",
            SCHEMA,
        )
    except llm.LLMError as e:
        log.warning("postcall LLM failed for %s: %s", meeting_id, e)
        return
    summary = str(out.get("summary") or "").strip()
    if not summary:
        log.warning("postcall: empty summary for %s", meeting_id)
        return
    decisions = [str(d) for d in out.get("decisions") or []]
    items = merge_action_items(meeting.get("action_items") or [], out.get("action_items") or [])
    updated = await db.update_meeting(
        meeting_id, summary=summary, decisions=decisions, action_items=items
    )
    # HACK: facts stored with embedding null; backfilled fire-and-forget below.
    for f in out.get("facts") or []:
        try:
            await db.insert_fact(meeting_id, f["speaker"], f["text"], f["kind"])
        except Exception:
            log.exception("postcall: insert_fact failed for %s", meeting_id)
    rag.backfill_later()
    await hub.publish(
        meeting_id,
        "meeting_ended",
        {"status": "done", "duration_min": _duration_min(updated or meeting)},
    )


def schedule_after_leave(meeting_id: str) -> None:
    """Fallback for a missing bot.done webhook: run once, LEAVE_DELAY_S after /leave."""

    async def later() -> None:
        await asyncio.sleep(LEAVE_DELAY_S)
        await run(meeting_id)

    task = asyncio.create_task(later())
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)

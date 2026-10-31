"""Recall realtime webhooks. `transcript.data` -> utterances row -> `utterance` WS event.

Payload (docs.recall.ai/docs/real-time-event-payloads):
{"event": "transcript.data", "data": {"data": {"words": [{"text", "start_timestamp":
{"relative": float}, "end_timestamp": {"relative": float} | null}], "language_code",
"participant": {"id": int, "name": str | null, ...}}, "bot": {...}, ...}}
"""

import asyncio
import logging
import secrets
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app import db, hub
from app.config import get_settings
from app.meetings import error_response

log = logging.getLogger(__name__)

BOT_MARKER = "call crew"  # our bot joins as "Call Crew (AI) for ..." (recall.BOT_NAME)

router = APIRouter()

# Strong refs so background tasks are not garbage-collected mid-flight.
_tasks: set[asyncio.Task] = set()


def _spawn(coro) -> asyncio.Task:
    task = asyncio.create_task(coro)
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    return task


def _token_ok(token: str | None) -> bool:
    expected = get_settings().WEBHOOK_TOKEN
    return bool(expected) and secrets.compare_digest((token or "").encode(), expected.encode())


async def orchestrator_hook(meeting_id: str, utterance: dict[str, Any]) -> None:
    """Called after every new utterance. No-op until M2.3 (the "Crew, ..." trigger)."""
    return None


def parse_transcript(payload: dict[str, Any]) -> dict[str, Any] | None:
    """Return {speaker, text, ts_start, ts_end} or None if the event should be ignored."""
    if payload.get("event") != "transcript.data":
        return None
    inner = (payload.get("data") or {}).get("data") or {}
    words = inner.get("words") or []
    text = " ".join(str(w.get("text", "")).strip() for w in words).strip()
    text = " ".join(text.split())
    if not text:
        return None
    participant = inner.get("participant") or {}
    name = (participant.get("name") or "").strip()
    if BOT_MARKER in name.lower():
        return None  # our own voice (SPEC "Ryzyka": agent reacting to itself)
    speaker = name or f"Participant {participant.get('id', '?')}"
    start = (words[0].get("start_timestamp") or {}).get("relative")
    end = (words[-1].get("end_timestamp") or {}).get("relative")
    return {
        "speaker": speaker,
        "text": text,
        "ts_start": float(start or 0.0),
        "ts_end": float(end) if end is not None else None,
    }


async def process_transcript(meeting_id: str, payload: dict[str, Any]) -> None:
    try:
        parsed = parse_transcript(payload)
        if parsed is None:
            return
        row = await db.insert_utterance(meeting_id, **parsed)
        if row is None:
            return  # Recall retry / duplicate: already stored and published
        utterance = {
            "id": row["id"],
            "speaker": row["speaker"],
            "text": row["text"],
            "ts": int(row["ts_start"]),
        }
        await hub.publish(meeting_id, "utterance", utterance)
        await orchestrator_hook(meeting_id, utterance)
    except Exception:
        log.exception("transcript processing failed for meeting %s", meeting_id)


@router.post("/webhooks/recall/transcript")
async def recall_transcript(request: Request, meeting_id: str = "", token: str = ""):
    if not _token_ok(token):
        return error_response(401, "unauthorized", "Missing or invalid token")
    try:
        payload = await request.json()
    except ValueError:
        return JSONResponse({"ok": True})
    if meeting_id and isinstance(payload, dict):
        _spawn(process_transcript(meeting_id, payload))
    return JSONResponse({"ok": True})


STATUS_MAP = {
    "bot.joining_call": "joining",
    "bot.in_waiting_room": "joining",
    "bot.in_call_not_recording": "in_call",
    "bot.in_call_recording": "in_call",
    "bot.done": "done",
    "bot.fatal": "failed",
}
FINAL = ("done", "failed")


async def postcall_hook(meeting_id: str) -> None:
    """Called once when the bot is done. No-op until M4.2."""
    return None  # TODO M4.2


async def process_status(payload: dict[str, Any]) -> None:
    try:
        event = payload.get("event")
        if event != "bot.call_ended" and event not in STATUS_MAP:
            return
        bot_id = (((payload.get("data") or {}).get("bot")) or {}).get("id")
        meeting = await db.get_meeting_by_bot(bot_id) if bot_id else None
        if meeting is None:
            log.info("status webhook: unknown bot %s, ignored", bot_id)
            return
        mid, current = meeting["id"], meeting["status"]
        now = datetime.now(UTC)
        fields: dict[str, Any] = {}
        if event == "bot.call_ended":
            if meeting.get("ended_at") is None:
                fields["ended_at"] = now
            new = current
        else:
            new = STATUS_MAP[event]
            if current in FINAL and new != current:
                return  # never leave a final state (late or out-of-order retry)
            if new == "in_call" and meeting.get("started_at") is None:
                fields["started_at"] = now
            if new in FINAL and meeting.get("ended_at") is None:
                fields["ended_at"] = now
        changed = new != current
        if changed:
            fields["status"] = new
        if fields:
            await db.update_meeting(mid, **fields)
        if changed:
            await hub.publish(mid, "meeting_status", {"status": new})
            if new == "done":
                await postcall_hook(mid)
    except Exception:
        log.exception("status processing failed")


@router.post("/webhooks/recall/status")
async def recall_status(request: Request, token: str = ""):
    if not _token_ok(token):
        return error_response(401, "unauthorized", "Missing or invalid token")
    try:
        payload = await request.json()
    except ValueError:
        return JSONResponse({"ok": True})
    if isinstance(payload, dict):
        _spawn(process_status(payload))
    return JSONResponse({"ok": True})

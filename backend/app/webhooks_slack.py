"""Slack Events API webhook: expert thread replies -> escalation.on_expert_reply.

Signature (decisions #19): `v0=` + hex HMAC-SHA256(SLACK_SIGNING_SECRET, `v0:{ts}:{raw body}`)
vs X-Slack-Signature, ts within 300 s. Filtering (decisions #20): skip retries
(X-Slack-Retry-Num), dedupe event_id, ignore bot messages and our own bot user.
"""

import asyncio
import hashlib
import hmac
import json
import logging
import time
from collections import OrderedDict
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app import escalation
from app.config import get_settings
from app.meetings import error_response
from app.notifier.slack import SLACK

log = logging.getLogger(__name__)

router = APIRouter()

MAX_SKEW_S = 300
DEDUPE_MAX = 1000
IGNORED_SUBTYPES = {"bot_message", "message_changed", "message_deleted", "message_replied"}

_tasks: set[asyncio.Task] = set()
_seen: OrderedDict[str, None] = OrderedDict()


def _spawn(coro) -> asyncio.Task:
    task = asyncio.create_task(coro)
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    return task


def reset() -> None:
    _seen.clear()


def verify_signature(body: bytes, timestamp: str | None, signature: str | None) -> bool:
    secret = get_settings().SLACK_SIGNING_SECRET
    if not secret or not timestamp or not signature:
        return False
    try:
        ts = int(timestamp)
    except ValueError:
        return False
    if abs(time.time() - ts) > MAX_SKEW_S:
        return False
    base = b"v0:" + timestamp.encode() + b":" + body
    expected = "v0=" + hmac.new(secret.encode(), base, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected.encode(), signature.encode())


def _first_time(event_id: str | None) -> bool:
    if not event_id:
        return True
    if event_id in _seen:
        return False
    _seen[event_id] = None
    while len(_seen) > DEDUPE_MAX:
        _seen.popitem(last=False)
    return True


def parse_reply(event: dict[str, Any]) -> tuple[str, str, str, str] | None:
    """(channel, thread_ts, text, user) for a human thread reply, else None."""
    if event.get("type") != "message":
        return None
    if event.get("bot_id") or event.get("subtype") in IGNORED_SUBTYPES:
        return None
    thread_ts, ts = event.get("thread_ts"), event.get("ts")
    if not thread_ts or thread_ts == ts:
        return None  # top-level DM, not a reply to our question
    channel, user = event.get("channel"), event.get("user")
    text = (event.get("text") or "").strip()
    if not channel or not user or not text:
        return None
    return channel, thread_ts, text, user


async def process_event(event: dict[str, Any]) -> None:
    try:
        reply = parse_reply(event)
        if reply is None:
            return
        channel, thread_ts, text, user = reply
        if user == await SLACK.bot_user_id():
            return
        await escalation.on_expert_reply(channel, thread_ts, text, user)
    except Exception:
        log.exception("slack event processing failed")


@router.post("/webhooks/slack")
async def slack_events(request: Request):
    body = await request.body()
    if not verify_signature(
        body,
        request.headers.get("X-Slack-Request-Timestamp"),
        request.headers.get("X-Slack-Signature"),
    ):
        return error_response(401, "unauthorized", "Invalid Slack signature")
    try:
        payload = json.loads(body)
    except ValueError:
        return JSONResponse({"ok": True})
    if not isinstance(payload, dict):
        return JSONResponse({"ok": True})
    if payload.get("type") == "url_verification":
        return JSONResponse({"challenge": payload.get("challenge", "")})
    if payload.get("type") != "event_callback":
        return JSONResponse({"ok": True})
    if request.headers.get("X-Slack-Retry-Num"):
        return JSONResponse({"ok": True})  # we already answered 200; retries are noise
    if not _first_time(payload.get("event_id")):
        return JSONResponse({"ok": True})
    event = payload.get("event")
    if isinstance(event, dict):
        _spawn(process_event(event))
    return JSONResponse({"ok": True})

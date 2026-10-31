"""Telegram webhook: expert replies -> escalation.on_expert_reply, `/start <expert_id>` linking.

Auth: header X-Telegram-Bot-Api-Secret-Token must equal TELEGRAM_WEBHOOK_SECRET (compare_digest);
no secret configured = reject (fail closed). Dedup on update_id, bots ignored, always 200 fast.
"""

import asyncio
import hmac
import logging
import re
from collections import OrderedDict
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app import db, escalation, orchestrator, runtime, telegram_api
from app.meetings import error_response

log = logging.getLogger(__name__)

router = APIRouter()

DEDUPE_MAX = 1000
START_RE = re.compile(r"^/start(?:@\w+)?(?:\s+([A-Za-z0-9_-]{1,64}))?\s*$")

_tasks: set[asyncio.Task] = set()
_seen: OrderedDict[int, None] = OrderedDict()


def _spawn(coro) -> asyncio.Task:
    task = asyncio.create_task(coro)
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    return task


def reset() -> None:
    _seen.clear()


def verify_secret(header: str | None) -> bool:
    secret = runtime.get("TELEGRAM_WEBHOOK_SECRET")
    if not secret or not header:
        return False
    return hmac.compare_digest(secret.encode(), header.encode())


def _first_time(update_id: Any) -> bool:
    if not isinstance(update_id, int):
        return True
    if update_id in _seen:
        return False
    _seen[update_id] = None
    while len(_seen) > DEDUPE_MAX:
        _seen.popitem(last=False)
    return True


async def _link(chat_id: str, expert_id: str) -> None:
    expert = await db.get_expert(expert_id)
    if expert is None:
        await telegram_api.send_message(chat_id, "Unknown link")
        return
    await db.update_expert(expert_id, telegram_chat_id=chat_id)
    orchestrator._experts_cache = None  # noqa: SLF001
    await escalation.load_experts(refresh=True)
    agent = runtime.get("AGENT_NAME")
    await telegram_api.send_message(chat_id, f"Linked: you'll get questions from {agent} here.")


async def process_update(update: dict[str, Any]) -> None:
    try:
        msg = update.get("message")
        if not isinstance(msg, dict):
            return
        sender = msg.get("from") or {}
        if sender.get("is_bot"):
            return
        chat_id = (msg.get("chat") or {}).get("id")
        text = (msg.get("text") or "").strip()
        if chat_id is None or not text:
            return
        chat_id = str(chat_id)
        m = START_RE.match(text)
        if m:
            if m.group(1):
                await _link(chat_id, m.group(1))
            return
        replied = msg.get("reply_to_message")
        if isinstance(replied, dict) and replied.get("message_id") is not None:
            await escalation.on_expert_reply(
                chat_id, str(replied["message_id"]), text, str(sender.get("id", ""))
            )
    except Exception:
        log.exception("telegram update processing failed")


@router.post("/webhooks/telegram")
async def telegram_webhook(request: Request):
    if not verify_secret(request.headers.get("X-Telegram-Bot-Api-Secret-Token")):
        return error_response(401, "unauthorized", "Invalid Telegram secret token")
    try:
        update = await request.json()
    except ValueError:
        return JSONResponse({"ok": True})
    if isinstance(update, dict) and _first_time(update.get("update_id")):
        _spawn(process_update(update))
    return JSONResponse({"ok": True})

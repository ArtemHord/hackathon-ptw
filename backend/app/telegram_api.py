"""Telegram Bot API client: the only module that talks to api.telegram.org.

POST https://api.telegram.org/bot<token>/<method> with JSON; responses are
{"ok": true, "result": ...} or {"ok": false, "description": "..."}. Errors never include the
request URL (it contains the bot token).
"""

import logging
from typing import Any

import httpx

from app import runtime

log = logging.getLogger(__name__)

API = "https://api.telegram.org"
TIMEOUT_S = 10.0

_bot_username: str | None = None


class TelegramError(RuntimeError):
    """Telegram could not be reached or answered ok:false."""


def configured() -> bool:
    return bool(runtime.get("TELEGRAM_BOT_TOKEN"))


def bot_username() -> str | None:
    """From the last successful getMe (cached)."""
    return _bot_username


def reset() -> None:
    global _bot_username
    _bot_username = None


async def call(method: str, payload: dict[str, Any] | None = None) -> Any:
    token = runtime.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise TelegramError("TELEGRAM_BOT_TOKEN is not set")
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_S) as client:
            r = await client.post(f"{API}/bot{token}/{method}", json=payload or {})
        data = r.json()
    except (httpx.HTTPError, ValueError) as e:
        raise TelegramError(f"telegram {method} failed: {e.__class__.__name__}") from None
    if not isinstance(data, dict) or not data.get("ok"):
        desc = data.get("description") if isinstance(data, dict) else "bad response"
        raise TelegramError(f"telegram {method}: {desc or r.status_code}")
    return data.get("result")


async def get_me() -> dict[str, Any]:
    global _bot_username
    me = await call("getMe")
    _bot_username = (me or {}).get("username") or _bot_username
    return me or {}


async def set_webhook(url: str, secret_token: str = "") -> None:
    payload: dict[str, Any] = {"url": url, "allowed_updates": ["message"]}
    if secret_token:
        payload["secret_token"] = secret_token
    await call("setWebhook", payload)


async def send_message(chat_id: str | int, text: str, **extra: Any) -> dict[str, Any]:
    """sendMessage; extra = reply_markup, reply_parameters, ... Returns the Message."""
    return await call("sendMessage", {"chat_id": chat_id, "text": text, **extra}) or {}

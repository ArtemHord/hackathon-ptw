"""Recall.ai client: the only module that talks to Recall (SPEC: "Jak agent wchodzi do ...")."""

import logging
from typing import Any
from urllib.parse import urlencode

import httpx

from app.config import get_settings

log = logging.getLogger(__name__)

BOT_NAME = f"{get_settings().AGENT_NAME} (AI) for Artem"  # HACK: owner name
WAITING_ROOM_TIMEOUT_S = 600
TIMEOUT = httpx.Timeout(20.0)


class RecallError(Exception):
    """Recall answered with an error or could not be reached."""

    def __init__(self, message: str, status: int | None = None, body: str = ""):
        super().__init__(message)
        self.status = status
        self.body = body


def _base() -> str:
    return get_settings().RECALL_BASE_URL.rstrip("/")


def _headers() -> dict[str, str]:
    # docs.recall.ai/docs/authentication: "Authorization: <key>", `Token ` prefix optional
    return {
        "Authorization": f"Token {get_settings().RECALL_API_KEY}",
        "Content-Type": "application/json",
    }


def _signed_url(path: str, meeting_id: str) -> str:
    s = get_settings()
    query = urlencode({"meeting_id": meeting_id, "token": s.WEBHOOK_TOKEN})
    return f"{s.PUBLIC_BASE_URL.rstrip('/')}{path}?{query}"


def _transcript_provider(provider: str) -> dict[str, Any]:
    """`recording_config.transcript.provider`. deepgram: nova-3 + keyterm boost for the wake word
    (docs.recall.ai/reference/bot_create, deepgram_streaming; keyterm is nova-3 only)."""
    if provider == "deepgram":
        return {
            "deepgram_streaming": {
                "model": "nova-3",
                "language": "en",
                "keyterm": get_settings().transcript_keyterms,
                # Deepgram default 10 ms splits "Atlas, what did" | "Artem finish" (live test 3)
                "endpointing": 500,
            }
        }
    return {"recallai_streaming": {"mode": "prioritize_low_latency", "language_code": "en"}}


def build_bot_body(
    meeting_url: str, meeting_id: str, provider: str | None = None
) -> dict[str, Any]:
    """Create Bot body: voice page (output_media) + low-latency realtime transcript in one call."""
    provider = provider or get_settings().TRANSCRIPT_PROVIDER
    return {
        "meeting_url": meeting_url,
        "bot_name": BOT_NAME,
        "output_media": {
            "camera": {
                "kind": "webpage",
                "config": {"url": _signed_url("/agent", meeting_id)},
            }
        },
        "variant": {
            "google_meet": "web_4_core",
            "zoom": "web_4_core",
            "microsoft_teams": "web_4_core",
        },
        "recording_config": {
            "transcript": {"provider": _transcript_provider(provider)},
            "realtime_endpoints": [
                {
                    "type": "webhook",
                    "url": _signed_url("/webhooks/recall/transcript", meeting_id),
                    "events": ["transcript.data"],
                }
            ],
        },
        "automatic_leave": {"waiting_room_timeout": WAITING_ROOM_TIMEOUT_S},
    }


async def _post(path: str, json: dict[str, Any] | None = None) -> httpx.Response:
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            r = await client.post(f"{_base()}{path}", headers=_headers(), json=json)
    except httpx.HTTPError as e:
        raise RecallError(f"Recall request failed: {e.__class__.__name__}") from e
    if r.status_code >= 400:
        raise RecallError(
            f"Recall {path} -> {r.status_code}: {r.text[:300]}", r.status_code, r.text[:1000]
        )
    return r


async def create_bot(meeting_url: str, meeting_id: str) -> dict[str, Any]:
    """POST /api/v1/bot/ and return Recall's bot object (has `id`).
    Deepgram rejected with 400 (e.g. no credentials in the dashboard) -> retry once with
    recallai_streaming so the bot always joins."""
    provider = get_settings().TRANSCRIPT_PROVIDER
    try:
        r = await _post("/api/v1/bot/", build_bot_body(meeting_url, meeting_id, provider))
    except RecallError as e:
        if provider != "deepgram" or e.status != 400:
            raise
        log.warning("recall rejected deepgram config, retrying with recallai: %s", e.body)
        r = await _post("/api/v1/bot/", build_bot_body(meeting_url, meeting_id, "recallai"))
    data = r.json()
    if not data.get("id"):
        raise RecallError("Recall create bot response has no id")
    return data


async def leave_call(bot_id: str) -> None:
    """POST /api/v1/bot/{id}/leave_call/ (decisions.md #18)."""
    await _post(f"/api/v1/bot/{bot_id}/leave_call/")


async def send_chat_message(bot_id: str | None, text: str) -> bool:
    """Best effort: POST /api/v1/bot/{id}/send_chat_message/ (decisions.md #17, confirmed R2).
    Google Meet caps chat at 500 chars. Never raises; logs and returns False on failure."""
    if not bot_id or not text:
        return False
    try:
        await _post(
            f"/api/v1/bot/{bot_id}/send_chat_message/", {"to": "everyone", "message": text[:500]}
        )
        return True
    except Exception as e:
        log.warning("recall chat message failed for bot %s: %s", bot_id, e)
        return False

"""The bot's "camera" page (SPEC "Strona agenta (/agent)") and its WebSocket.

Recall's bot browser opens `{PUBLIC_BASE_URL}/agent?meeting_id=&token=`; the page connects
to `/agent-page/ws`, plays the mp3 we push into the call and reports `speaking` back.
Single instance: sockets and speaking flags live in this process (like hub.py).

Server -> page: {"type":"play","id","audio_b64","text"?} | {"type":"tone","id"}
               | {"type":"state","state":"idle"|"listening"|"thinking"|"speaking"}   (orb, M2.5)
               | {"type":"ask","id","question","expert","timeout_s"}
               | {"type":"ask_done","id","result":"answered"|"timeout"}
Page -> server: {"type":"speaking","value":bool,"id"}
"""

import base64
import logging
import time
import uuid
from collections import defaultdict
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse

from app.meetings import error_response
from app.webhooks_recall import _token_ok  # WEBHOOK_TOKEN, constant-time

log = logging.getLogger(__name__)

WS_UNAUTHORIZED = 4401
SPEAKING_TTL_S = 90.0  # a speaking=true older than this is stale (lost page / missed false)
PAGE_DIR = Path(__file__).resolve().parent.parent / "agent_page"
PAGE = PAGE_DIR / "index.html"
ORB_JS = PAGE_DIR / "orb.js"
# Whitelist, not a directory mount: no path traversal, explicit font types.
ASSETS = {
    "DrukWideCyr.ttf": "font/ttf",
    "Onest-latin.woff2": "font/woff2",
    "JetBrainsMono-latin.woff2": "font/woff2",
}
ORB_STATES = frozenset({"idle", "listening", "thinking", "speaking"})
ASK_RESULTS = frozenset({"answered", "timeout"})

_pages: dict[str, set[WebSocket]] = defaultdict(set)
_speaking: dict[str, tuple[bool, float]] = {}  # meeting_id -> (value, monotonic ts)

router = APIRouter()


def connected(meeting_id: str) -> int:
    return len(_pages.get(meeting_id, ()))


def is_speaking(meeting_id: str) -> bool:
    """True while the page is playing our audio (M2.3 ignores our own voice then)."""
    value, ts = _speaking.get(meeting_id, (False, 0.0))
    return value and time.monotonic() - ts <= SPEAKING_TTL_S


def _set_speaking(meeting_id: str, value: bool) -> None:
    _speaking[meeting_id] = (value, time.monotonic())


def _discard(meeting_id: str, ws: WebSocket) -> None:
    # Any socket going away clears the flag; a live page re-reports it on (re)connect.
    _speaking.pop(meeting_id, None)
    group = _pages.get(meeting_id)
    if group is not None:
        group.discard(ws)
        if not group:
            _pages.pop(meeting_id, None)


async def _send(meeting_id: str, msg: dict[str, Any]) -> bool:
    sent = False
    for ws in list(_pages.get(meeting_id, ())):
        try:
            await ws.send_json(msg)
            sent = True
        except Exception as e:  # dead socket: drop it, keep the others
            log.info("agent page: dropping socket for %s: %s", meeting_id, e.__class__.__name__)
            _discard(meeting_id, ws)
    return sent


async def play(meeting_id: str, mp3: bytes, text: str | None = None) -> bool:
    """Push mp3 audio to the agent page. False if no page is connected."""
    msg: dict[str, Any] = {
        "type": "play",
        "id": uuid.uuid4().hex[:12],
        "audio_b64": base64.b64encode(mp3).decode("ascii"),
    }
    if text:
        msg["text"] = text
    return await _send(meeting_id, msg)


async def play_test_tone(meeting_id: str) -> bool:
    """The page synthesises a short WebAudio beep: checks the audio path without TTS."""
    return await _send(meeting_id, {"type": "tone", "id": uuid.uuid4().hex[:12]})


async def _send_safe(meeting_id: str, msg: dict[str, Any]) -> bool:
    try:
        return await _send(meeting_id, msg)
    except Exception as e:  # orb visuals must never break the caller
        log.warning("agent page: %s send failed for %s: %s", msg.get("type"), meeting_id, e)
        return False


async def send_state(meeting_id: str, state: str) -> bool:
    """Orb state: idle | listening | thinking | speaking. False if unknown or no page."""
    if state not in ORB_STATES:
        log.warning("agent page: unknown orb state %r", state)
        return False
    return await _send_safe(meeting_id, {"type": "state", "state": state})


async def send_ask(
    meeting_id: str, esc_id: str, question: str, expert: str, timeout_s: int | float
) -> bool:
    """Orb ask sequence: question types out, plate 'ASKING <EXPERT> ON SLACK' drains."""
    try:
        timeout = int(timeout_s)
    except (TypeError, ValueError):
        timeout = 120
    msg = {
        "type": "ask",
        "id": str(esc_id),
        "question": str(question),
        "expert": str(expert),
        "timeout_s": timeout,
    }
    return await _send_safe(meeting_id, msg)


async def send_ask_done(meeting_id: str, esc_id: str, result: str) -> bool:
    """End the ask sequence: 'answered' (coral flash -> thinking) or 'timeout' (-> idle)."""
    if result not in ASK_RESULTS:
        log.warning("agent page: unknown ask result %r", result)
        return False
    return await _send_safe(meeting_id, {"type": "ask_done", "id": str(esc_id), "result": result})


@router.get("/agent", include_in_schema=False)
async def agent_page() -> FileResponse:
    # No auth: the page reads meeting_id and token from its own query string.
    return FileResponse(PAGE, media_type="text/html", headers={"Cache-Control": "no-store"})


@router.get("/agent/orb.js", include_in_schema=False)
async def agent_orb_js() -> FileResponse:
    return FileResponse(ORB_JS, media_type="text/javascript", headers={"Cache-Control": "no-store"})


@router.get("/agent/assets/{name}", include_in_schema=False)
async def agent_asset(name: str) -> FileResponse:
    media_type = ASSETS.get(name)
    if media_type is None:
        raise HTTPException(status_code=404)
    return FileResponse(
        PAGE_DIR / "assets" / name,
        media_type=media_type,
        headers={"Cache-Control": "public, max-age=86400"},
    )


@router.websocket("/agent-page/ws")
async def agent_page_ws(ws: WebSocket, meeting_id: str = "", token: str = "") -> None:
    await ws.accept()  # accept first so the page actually receives the 4401 close code
    if not _token_ok(token) or not meeting_id:
        await ws.close(code=WS_UNAUTHORIZED)
        return
    _speaking.pop(meeting_id, None)  # fresh page: drop any flag left by a half-open socket
    _pages[meeting_id].add(ws)
    log.info("agent page connected for %s (%d)", meeting_id, connected(meeting_id))
    try:
        while True:
            try:
                msg = await ws.receive_json()
            except (ValueError, KeyError):
                continue  # junk frame: ignore
            if isinstance(msg, dict) and msg.get("type") == "speaking":
                _set_speaking(meeting_id, bool(msg.get("value")))
    except WebSocketDisconnect:
        pass
    finally:
        _discard(meeting_id, ws)


# HACK: debug-only, not in the app contract (docs/API.pl.md). Checks audio reaches the call.
@router.post("/debug/say-tone", include_in_schema=False)
async def debug_say_tone(meeting_id: str = "", token: str = ""):
    if not _token_ok(token):
        return error_response(401, "unauthorized", "Missing or invalid token")
    delivered = await play_test_tone(meeting_id) if meeting_id else False
    return JSONResponse({"ok": True, "delivered": delivered, "pages": connected(meeting_id)})

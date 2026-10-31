"""In-memory WebSocket hub for the app's Live screen (docs/API.pl.md "WebSocket: /app/ws").

Single instance, no queues: sockets are kept per meeting_id in this process.
"""

import logging
import secrets
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.config import get_settings

log = logging.getLogger(__name__)

WS_UNAUTHORIZED = 4401

_clients: dict[str, set[WebSocket]] = defaultdict(set)

router = APIRouter()


def _now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def envelope(meeting_id: str, type_: str, data: dict[str, Any]) -> dict[str, Any]:
    return {"type": type_, "meeting_id": meeting_id, "ts": _now_iso(), "data": data}


def subscribers(meeting_id: str) -> int:
    return len(_clients.get(meeting_id, ()))


async def publish(meeting_id: str, type_: str, data: dict[str, Any]) -> int:
    """Send one envelope to every socket on this meeting. Returns how many got it."""
    msg = envelope(meeting_id, type_, data)
    sent = 0
    for ws in list(_clients.get(meeting_id, ())):
        try:
            await ws.send_json(msg)
            sent += 1
        except Exception as e:  # dead socket: drop it, keep the others
            log.info("hub: dropping socket for %s: %s", meeting_id, e.__class__.__name__)
            _discard(meeting_id, ws)
    return sent


def _discard(meeting_id: str, ws: WebSocket) -> None:
    group = _clients.get(meeting_id)
    if group is not None:
        group.discard(ws)
        if not group:
            _clients.pop(meeting_id, None)


def _token_ok(token: str | None) -> bool:
    expected = get_settings().DEMO_TOKEN
    return bool(expected) and secrets.compare_digest((token or "").encode(), expected.encode())


@router.websocket("/app/ws")
async def app_ws(ws: WebSocket, meeting_id: str = "", token: str = "") -> None:
    # Accept first so the client actually receives the 4401 close code (API.pl.md).
    await ws.accept()
    if not _token_ok(token) or not meeting_id:
        await ws.close(code=WS_UNAUTHORIZED)
        return
    _clients[meeting_id].add(ws)
    try:
        while True:  # the app sends nothing meaningful; we only watch for disconnect
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        _discard(meeting_id, ws)

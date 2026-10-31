"""App endpoints for meetings (docs/API.pl.md): POST /meetings, POST /meetings/{id}/leave."""

import logging
import secrets
from datetime import UTC, datetime
from typing import Any, Literal
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, FastAPI, Header, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app import db, recall
from app.config import get_settings

log = logging.getLogger(__name__)


# --- errors in the API.pl.md format: {"error": {"code", "message"}} ----------


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str):
        self.status, self.code, self.message = status, code, message


def error_response(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": message}})


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(_: Request, e: ApiError) -> JSONResponse:
        return error_response(e.status, e.code, e.message)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, e: RequestValidationError) -> JSONResponse:
        first = e.errors()[0] if e.errors() else {}
        where = ".".join(str(p) for p in first.get("loc", ()))
        return error_response(422, "validation_error", f"{where}: {first.get('msg', 'invalid')}")


# --- auth ---------------------------------------------------------------------


async def require_demo_token(authorization: str | None = Header(default=None)) -> None:
    """`Authorization: Bearer <DEMO_TOKEN>`; reusable for every app endpoint."""
    expected = get_settings().DEMO_TOKEN
    scheme, _, token = (authorization or "").partition(" ")
    if (
        not expected
        or scheme.lower() != "bearer"
        or not secrets.compare_digest(token.strip().encode(), expected.encode())
    ):
        raise ApiError(401, "unauthorized", "Missing or invalid token")


router = APIRouter(dependencies=[Depends(require_demo_token)])


# --- helpers ------------------------------------------------------------------


def detect_platform(meeting_url: str) -> str | None:
    """API enum: google_meet | zoom | teams."""
    host = (urlsplit(meeting_url.strip()).hostname or "").lower()
    if host == "meet.google.com":
        return "google_meet"
    if host == "zoom.us" or host.endswith(".zoom.us"):
        return "zoom"
    if host in ("teams.microsoft.com", "teams.live.com") or host.endswith(".teams.microsoft.com"):
        return "teams"
    return None


def iso(dt: datetime | None) -> str | None:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ") if dt else None


class MeetingCreate(BaseModel):
    meeting_url: str
    mode: Literal["notetaker", "delegate"] = "notetaker"
    brief: str | None = None
    title: str | None = None


# --- endpoints ----------------------------------------------------------------


@router.post("/meetings", status_code=201)
async def create_meeting(body: MeetingCreate) -> dict[str, Any]:
    platform = detect_platform(body.meeting_url)
    if platform is None:
        raise ApiError(400, "bad_request", "meeting_url must be a Google Meet, Zoom or Teams link")

    m = await db.insert_meeting(
        title=(body.title or "").strip(),
        platform=platform,
        meeting_url=body.meeting_url.strip(),
        mode=body.mode,
        status="joining",
        started_at=datetime.now(UTC),
    )
    if body.mode == "delegate" and body.brief and body.brief.strip():
        await db.insert_brief(m["id"], body.brief.strip())

    try:
        bot = await recall.create_bot(m["meeting_url"], m["id"])
    except recall.RecallError as e:
        log.warning("Recall create_bot failed for %s: %s", m["id"], e)
        await db.update_meeting(m["id"], status="failed")
        raise ApiError(502, "upstream_error", "Recall could not create the bot") from e

    await db.update_meeting(m["id"], recall_bot_id=bot["id"])
    return {
        "id": m["id"],
        "status": "joining",
        "title": m["title"],
        "platform": m["platform"],
        "mode": m["mode"],
        "started_at": iso(m["started_at"]),
    }


@router.post("/meetings/{meeting_id}/leave")
async def leave_meeting(meeting_id: str) -> dict[str, Any]:
    m = await db.get_meeting(meeting_id)
    if m is None:
        raise ApiError(404, "not_found", f"Meeting {meeting_id} not found")
    if m.get("recall_bot_id") and m.get("status") not in ("done", "failed"):
        try:
            await recall.leave_call(m["recall_bot_id"])
        except recall.RecallError as e:
            log.warning("Recall leave_call failed for %s: %s", meeting_id, e)
            raise ApiError(502, "upstream_error", "Recall could not remove the bot") from e
    # DB status stays as is until the bot.done webhook (M1.3) flips it to done.
    # TODO M4.2 postcall: post-call summary starts on bot.done (decisions.md #16), not here.
    return {"id": meeting_id, "status": "done", "summary_status": "processing"}

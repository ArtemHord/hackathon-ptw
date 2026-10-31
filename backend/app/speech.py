"""Voice out: POST /tts (app, "Odsłuchaj"), say() into the call, HACK /debug/say."""

import logging

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field, field_validator

from app import agent_voice, tts
from app.meetings import ApiError, error_response, require_demo_token
from app.webhooks_recall import _token_ok

log = logging.getLogger(__name__)

router = APIRouter()


class TextBody(BaseModel):
    text: str = Field(max_length=1000)

    @field_validator("text")
    @classmethod
    def _non_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("must not be empty")
        return v


async def say(meeting_id: str, text: str) -> bool:
    """Synthesize and play in the call (text shown as caption). False on any failure."""
    try:
        mp3 = await tts.synthesize(text)
        return await agent_voice.play(meeting_id, mp3, text=text)
    except Exception as e:  # never raise into the orchestrator
        log.warning("say(%s) failed: %s", meeting_id, e)
        return False


async def say_filler(meeting_id: str) -> bool:
    try:
        mp3 = await tts.filler()
        return await agent_voice.play(meeting_id, mp3, text=tts.FILLER_TEXT)
    except Exception as e:  # never raise into the orchestrator
        log.warning("say_filler(%s) failed: %s", meeting_id, e)
        return False


@router.post("/tts", dependencies=[Depends(require_demo_token)])
async def post_tts(body: TextBody) -> Response:
    try:
        mp3 = await tts.synthesize(body.text)
    except tts.TTSError as e:
        raise ApiError(502, "upstream_error", str(e)) from e
    return Response(content=mp3, media_type="audio/mpeg")


# HACK: live-test helper, not in the app contract (docs/API.pl.md).
@router.post("/debug/say", include_in_schema=False)
async def debug_say(body: TextBody, meeting_id: str = "", token: str = ""):
    if not _token_ok(token):
        return error_response(401, "unauthorized", "Missing or invalid token")
    delivered = await say(meeting_id, body.text) if meeting_id else False
    return JSONResponse({"ok": True, "delivered": delivered})

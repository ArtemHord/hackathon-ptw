"""HACK: debug endpoints to drive the escalation loop without Slack. Not in API.pl.md."""

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from app import db, escalation
from app.meetings import error_response
from app.webhooks_recall import _token_ok

router = APIRouter(prefix="/debug")


class ExpertReply(BaseModel):
    escalation_id: str
    text: str


@router.post("/expert-reply")
async def expert_reply(body: ExpertReply, token: str | None = None) -> Any:
    if not _token_ok(token):
        return error_response(401, "unauthorized", "Missing or invalid token")
    esc = await db.get_escalation(body.escalation_id)
    if esc is None:
        return error_response(404, "not_found", "Unknown escalation")
    if not esc.get("external_msg_id"):
        return error_response(409, "not_delivered", "Question not sent to the expert yet")
    await escalation.on_expert_reply(
        esc.get("external_channel_id") or "", esc["external_msg_id"], body.text, "debug"
    )
    return {"ok": True}


@router.get("/escalations")
async def list_escalations(meeting_id: str | None = None, token: str | None = None) -> Any:
    if not _token_ok(token):
        return error_response(401, "unauthorized", "Missing or invalid token")
    rows = await db.list_escalations(meeting_id)
    return [{"id": str(r["id"]), "status": r["status"], "expert": r.get("expert")} for r in rows]

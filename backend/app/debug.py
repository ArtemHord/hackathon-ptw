"""HACK: debug endpoints to drive the escalation loop without Slack. Not in API.pl.md.

Auth: `?token=WEBHOOK_TOKEN` (scripts) or `Authorization: Bearer DEMO_TOKEN` (web UI).
"""

from typing import Any

from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel, Field

from app import db, escalation, orchestrator, profile, simulate
from app.config import get_settings
from app.meetings import ApiError, demo_token_ok, error_response
from app.webhooks_recall import _spawn, _token_ok


async def require_debug_token(
    token: str | None = None, authorization: str | None = Header(default=None)
) -> None:
    if not (_token_ok(token) or demo_token_ok(authorization)):
        raise ApiError(401, "unauthorized", "Missing or invalid token")


router = APIRouter(prefix="/debug", dependencies=[Depends(require_debug_token)])


class AskBody(BaseModel):
    text: str | None = None


class ExpertReply(BaseModel):
    escalation_id: str
    text: str


class SimulateBody(BaseModel):
    speed: float = simulate.DEFAULT_SPEED
    expert_reply: str | None = Field(default_factory=profile.sim_default_reply)


@router.post("/expert-reply")
async def expert_reply(body: ExpertReply) -> Any:
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
async def list_escalations(meeting_id: str | None = None) -> Any:
    rows = await db.list_escalations(meeting_id)
    return [{"id": str(r["id"]), "status": r["status"], "expert": r.get("expert")} for r in rows]


@router.post("/ask")
async def ask(meeting_id: str, body: AskBody | None = None) -> Any:
    """HACK (M6.3): stage backup trigger when the ASR mangles the wake word. Runs the answer flow
    on body.text, or on the latest human utterance of the meeting. No wake-word check;
    the speaking / busy / delegate-mode guards still apply (inside orchestrator.ask)."""
    asked = await orchestrator.manual_question(meeting_id, body.text if body else None)
    if asked is None:
        return error_response(404, "not_found", "No utterance to answer")
    utterance, question = asked
    _spawn(orchestrator.ask(meeting_id, utterance, question))  # 200 now, voice follows
    return {"ok": True, "question": question}


@router.post("/simulate", status_code=202)
async def simulate_call(body: SimulateBody | None = None) -> Any:
    """Replay the demo transcript as Recall webhooks to ourselves (no Recall, no real call)."""
    if not get_settings().DATABASE_URL:
        raise ApiError(409, "conflict", "Simulation needs a database")
    if not get_settings().WEBHOOK_TOKEN:
        raise ApiError(409, "conflict", "Simulation needs WEBHOOK_TOKEN")
    body = body or SimulateBody()
    speed = min(max(body.speed, 0.5), 200.0)
    meeting_id = await simulate.run(speed=speed, expert_reply=body.expert_reply)
    return {"meeting_id": meeting_id}

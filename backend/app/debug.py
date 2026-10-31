"""HACK: debug endpoints to drive the escalation loop without Slack. Not in API.pl.md."""

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from app import db, escalation, orchestrator
from app.meetings import error_response
from app.webhooks_recall import _spawn, _token_ok, is_bot_speaker

router = APIRouter(prefix="/debug")


class AskBody(BaseModel):
    text: str | None = None


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


@router.post("/ask")
async def ask(meeting_id: str, token: str | None = None, body: AskBody | None = None) -> Any:
    """HACK (M6.3): stage backup trigger when the ASR mangles the wake word. Runs the answer flow
    on body.text, or on the latest human utterance of the meeting. No wake-word check;
    the speaking / busy / delegate-mode guards still apply (inside orchestrator.ask)."""
    if not _token_ok(token):
        return error_response(401, "unauthorized", "Missing or invalid token")
    last = [
        u
        for u in await db.get_last_utterances(meeting_id, 10)
        if not is_bot_speaker(str(u.get("speaker") or ""))
    ]
    latest = last[-1] if last else None
    text = ((body.text if body else None) or "").strip()
    if not text:
        if latest is None:
            return error_response(404, "not_found", "No utterance to answer")
        text = str(latest.get("text") or "").strip()
    question = orchestrator.parse_trigger(text) or text
    utterance = {
        "id": latest.get("id") if latest else None,
        "speaker": (latest or {}).get("speaker") or "Someone",
        "text": text,
        "ts": int(float((latest or {}).get("ts_start") or 0.0)),
    }
    _spawn(orchestrator.ask(meeting_id, utterance, question))  # 200 now, voice follows
    return {"ok": True, "question": question}

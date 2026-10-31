"""App endpoints: GET/POST /kb/docs (docs/API.pl.md)."""

from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, UploadFile

from app import db, llm, rag
from app.meetings import ApiError, iso, require_demo_token

router = APIRouter(dependencies=[Depends(require_demo_token)])
MAX_BYTES = 1_000_000


@router.get("/kb/docs")
async def get_docs() -> dict:
    return {"items": await rag.list_docs()}


@router.post("/kb/docs", status_code=201)
async def post_doc(
    file: Annotated[UploadFile, File()], title: Annotated[str | None, Form()] = None
) -> dict:
    raw = await file.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ApiError(413, "too_large", "File too large (max 1 MB)")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise ApiError(400, "invalid_file", "File must be UTF-8 text") from None
    name = (title or file.filename or "").strip()
    if not name or not text.strip():
        raise ApiError(400, "invalid_file", "Need a non-empty .md file with a title")
    try:
        return await rag.upsert_doc(name, text)
    except llm.LLMError as e:
        raise ApiError(502, "embedding_failed", str(e)) from e


def _proposal_item(p: dict) -> dict:
    # HACK: no reason column; derive it from the speaker.
    who = p["speaker"] or "Someone"
    return {
        "id": p["id"],
        "doc_id": p["doc_id"],
        "doc_title": p["doc_title"],
        "status": p["status"],
        "created_at": iso(p["created_at"]),
        "meeting_id": p["meeting_id"],
        "ts": int(p["ts"]) if p["ts"] is not None else None,
        "speaker": p["speaker"],
        "reason": f"{who} said this on the call.",
        "old_text": p["old_text"],
        "new_text": p["new_text"],
    }


@router.get("/kb/proposals")
async def get_proposals(status: str | None = None) -> dict:
    items = await db.list_proposals(include_all=status == "all")
    return {"items": [_proposal_item(p) for p in items]}


@router.post("/kb/proposals/{proposal_id}/approve")
async def approve_proposal(proposal_id: str) -> dict:
    """A second approve (or approve after reject) returns 409 conflict."""
    outcome, res = await rag.apply_proposal(proposal_id)
    if outcome == "missing":
        raise ApiError(404, "not_found", "Proposal not found")
    if outcome == "not_pending":
        raise ApiError(409, "conflict", "Proposal already resolved")
    if outcome == "text_not_found" or res is None:
        raise ApiError(409, "conflict", "The old text is no longer in the document")
    return {"id": proposal_id, "status": "approved", **res}


@router.post("/kb/proposals/{proposal_id}/reject")
async def reject_proposal(proposal_id: str) -> dict:
    p = await db.get_proposal(proposal_id)
    if not p:
        raise ApiError(404, "not_found", "Proposal not found")
    if not await db.reject_proposal(proposal_id):
        raise ApiError(409, "conflict", "Proposal already resolved")
    return {"id": proposal_id, "status": "rejected", "doc_id": p["doc_id"], "doc_version": None}

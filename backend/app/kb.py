"""App endpoints: GET/POST /kb/docs (docs/API.pl.md)."""

from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, UploadFile

from app import llm, rag
from app.meetings import ApiError, require_demo_token

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

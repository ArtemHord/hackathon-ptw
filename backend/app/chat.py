"""POST /chat (app screen 5): answer from kb + facts + utterances, with citations."""

import logging
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app import db, llm, rag
from app.meetings import require_demo_token

log = logging.getLogger(__name__)

router = APIRouter(dependencies=[Depends(require_demo_token)])

NOT_FOUND = "I couldn't find that in your calls or docs."
SCHEMA = {
    "type": "object",
    "properties": {
        "answer": {"type": "string"},
        "used": {"type": "array", "items": {"type": "integer"}},
    },
    "required": ["answer", "used"],
    "additionalProperties": False,
}
SYSTEM = (
    "You answer questions about the user's past calls and documents. Answer ONLY from the "
    "numbered sources below; never use outside knowledge and never make commitments or "
    "deadlines. Reply in English, concisely. Return JSON {answer, used} where used lists the "
    "numbers of the sources you relied on. If the sources do not contain the answer, say so "
    "and return used: []."
)


class ChatBody(BaseModel):
    question: str = Field(min_length=1, max_length=500)


async def _ts_for(item: dict[str, Any]) -> int:
    """Utterance ts as-is; facts have none -> first utterance by the same speaker, else 0."""
    if item.get("ts") is not None:
        return int(item["ts"])
    try:
        for u in await db.get_all_utterances(item["meeting_id"]):
            if u["speaker"] == item.get("speaker"):
                return int(u["ts_start"])
        ans = await db.answered_ts_for_expert(item["meeting_id"], item.get("speaker") or "")
        if ans is not None:
            return ans
    except Exception:
        log.exception("chat: ts fallback failed")
    return 0


async def _citation(item: dict[str, Any]) -> dict[str, Any] | None:
    if item["kind"] == "kb":
        doc = await db.kb_doc_by_title(item["doc_title"])
        if not doc:
            return None
        return {
            "type": "document",
            "doc_id": doc["id"],
            "title": doc["title"],
            "version": doc["version"],
        }
    return {
        "type": "meeting",
        "meeting_id": item["meeting_id"],
        "ts": await _ts_for(item),
        "speaker": item.get("speaker") or "",
        "text": item["text"],
    }


async def _save(role: str, text: str, citations: list[dict[str, Any]]) -> None:
    try:
        await db.insert_chat_message(role, text, citations)
    except Exception:
        log.exception("chat: saving message failed")


@router.post("/chat")
async def chat(body: ChatBody) -> dict[str, Any]:
    await _save("user", body.question, [])
    answer, citations = NOT_FOUND, []
    try:
        items = await rag.search(body.question, k=8)
        if items:
            sources = "\n".join(f"[{i}] {it['text']}" for i, it in enumerate(items, 1))
            prompt = f"Sources:\n{sources}\n\nQuestion: {body.question}"
            out = await llm.chat_json(
                [
                    {"role": "system", "content": SYSTEM},
                    {"role": "user", "content": prompt},
                ],
                "chat_answer",
                SCHEMA,
            )
            text = str(out.get("answer") or "").strip()
            if text:
                answer = text
                seen: set[int] = set()
                for n in out.get("used") or []:
                    if not isinstance(n, int) or n in seen or not 1 <= n <= len(items):
                        continue
                    seen.add(n)
                    c = await _citation(items[n - 1])
                    if c:
                        citations.append(c)
    except Exception:
        log.exception("chat failed")
        answer, citations = NOT_FOUND, []
    await _save("assistant", answer, citations)
    return {"answer": answer, "citations": citations}

"""Knowledge base: chunking, embeddings, upsert and cosine search (SPEC: top-k 6)."""

import asyncio
import logging
from typing import Any

from app import db, llm

log = logging.getLogger(__name__)

CHUNK_CHARS = 2400  # ~600 tokens at ~4 chars/token (SPEC: 500-800)
OVERLAP_CHARS = 320  # ~80 tokens
BACKFILL_BATCH = 200

_tasks: set[asyncio.Task] = set()


def _units(text: str, size: int) -> list[str]:
    """Paragraphs; a paragraph longer than `size` is cut at whitespace/hard."""
    out: list[str] = []
    for para in (p.strip() for p in text.replace("\r\n", "\n").split("\n\n")):
        while len(para) > size:
            cut = para.rfind(" ", 0, size)
            cut = cut if cut > size // 2 else size
            out.append(para[:cut].strip())
            para = para[cut:].strip()
        if para:
            out.append(para)
    return out


def chunk_text(text: str, size: int = CHUNK_CHARS, overlap: int = OVERLAP_CHARS) -> list[str]:
    """Chunks <= size chars on paragraph boundaries; each starts with the previous tail."""
    chunks: list[str] = []
    cur = ""
    fresh = True  # cur holds only overlap so far
    for u in _units(text, size - overlap):
        joined = f"{cur}\n\n{u}" if cur else u
        if len(joined) <= size:
            cur, fresh = joined, False
            continue
        if not fresh:
            chunks.append(cur)
            tail = cur[-overlap:]
            cur = f"{tail}\n\n{u}" if len(tail) + 2 + len(u) <= size else u
        else:
            cur = u
        fresh = False
    if cur and not fresh:
        chunks.append(cur)
    return chunks


async def upsert_doc(title: str, markdown: str) -> dict[str, Any]:
    """Chunk + embed + store. Same title -> version bump, chunks replaced."""
    chunks = chunk_text(markdown)
    if not chunks:
        raise ValueError("empty document")
    embeddings = await llm.embed(chunks)
    return await db.upsert_kb_doc(title, chunks, embeddings)


async def list_docs() -> list[dict[str, Any]]:
    docs = await db.list_kb_docs()
    out = []
    for d in docs:
        # HACK: no version history table; only the current and first version have real times.
        versions = [
            {"version": v, "updated_at": d["created_at"] if v == 1 else d["updated_at"]}
            for v in range(1, d["version"] + 1)
        ]
        out.append(
            {
                "id": d["id"],
                "title": d["title"],
                "version": d["version"],
                "updated_at": d["updated_at"],
                "chunks": d["chunks"],
                "versions": versions,
            }
        )
    return out


async def search(
    query: str, k: int = 6, kinds: tuple[str, ...] = ("kb", "facts", "utterances")
) -> list[dict[str, Any]]:
    """Items {kind, text, score, doc_title|meeting_id, ts, speaker}, best first."""
    (qvec,) = await llm.embed([query])
    rows = await db.vector_search(qvec, k, kinds)
    items = []
    for r in rows:
        item: dict[str, Any] = {"kind": r["kind"], "text": r["text"], "score": float(r["score"])}
        if r["kind"] == "kb":
            item["doc_title"] = r["doc_title"]
        else:
            item.update(meeting_id=r["meeting_id"], ts=r["ts"], speaker=r["speaker"])
        items.append(item)
    return items


async def backfill_embeddings() -> int:
    """Embed facts and utterances that have embedding null. Returns rows updated."""
    total = 0
    for table in ("facts", "utterances"):
        while True:
            rows = await db.rows_without_embedding(table, BACKFILL_BATCH)
            if not rows:
                break
            vecs = await llm.embed([r["text"] for r in rows])
            await db.set_embeddings(table, [(r["id"], v) for r, v in zip(rows, vecs, strict=True)])
            total += len(rows)
            if len(rows) < BACKFILL_BATCH:
                break
    return total


def backfill_later() -> None:
    """Fire-and-forget backfill; never raises."""

    async def go() -> None:
        try:
            await backfill_embeddings()
        except Exception:
            log.exception("embedding backfill failed")

    task = asyncio.create_task(go())
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


async def _embed_one(text: str) -> list[float]:
    return (await llm.embed([text]))[0]


async def apply_proposal(proposal_id: str) -> tuple[str, dict[str, Any] | None]:
    """Approve a KB proposal: exact-substring replace in its chunk, re-embed (best effort),
    bump versions. Returns (outcome, {doc_id, doc_version}); see db.approve_proposal."""
    return await db.approve_proposal(proposal_id, _embed_one)

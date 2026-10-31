"""Upsert backend/seed/{api,roadmap,team}.md into the knowledge base (idempotent).

Usage: cd backend && uv run python ../scripts/seed_kb.py
Needs DATABASE_URL and OPENAI_API_KEY in env/.env. Same code path as POST /kb/docs.
Re-running skips docs whose content is unchanged (no version bump).
"""

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from app import db, rag  # noqa: E402
from app.config import get_settings  # noqa: E402

SEED = ROOT / "backend" / "seed"
FILES = ("api.md", "roadmap.md", "team.md", "customers.md")


async def upsert_file(path: Path) -> None:
    """One markdown file as a KB doc titled by its file name; skipped when unchanged.
    Shared with seed_msp.py. Pool must be open."""
    name = path.name
    text = path.read_text(encoding="utf-8")
    chunks = rag.chunk_text(text)
    existing = await db.kb_doc_by_title(name)
    if existing:
        pool = await db.get_pool()
        stored = await pool.fetch(
            "select text from kb_chunks where doc_id = $1 order by created_at, id",
            existing["id"],
        )
        if sorted(r["text"] for r in stored) == sorted(chunks):
            print(f"{name}: unchanged (v{existing['version']})")
            return
    doc = await rag.upsert_doc(name, text)
    print(f"{name}: v{doc['version']}, {doc['chunks']} chunks")


async def main() -> None:
    s = get_settings()
    if not (s.DATABASE_URL and s.OPENAI_API_KEY):
        sys.exit("DATABASE_URL and OPENAI_API_KEY are required")
    try:
        for name in FILES:
            await upsert_file(SEED / name)
    finally:
        await db.close_pool()


if __name__ == "__main__":
    asyncio.run(main())

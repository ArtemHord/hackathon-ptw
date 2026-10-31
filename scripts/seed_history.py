"""Seed two backdated past meetings (backend/seed/history.json) for the memory demo.

Usage: cd backend && uv run python ../scripts/seed_history.py
Idempotent: fixed meeting ids, fixed fact ids, utterances unique on (meeting, speaker, ts).
Then embeds the new facts/utterances (needs OPENAI_API_KEY).
"""

import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from app import db, rag  # noqa: E402
from app.config import get_settings  # noqa: E402

HISTORY = ROOT / "backend" / "seed" / "history.json"


async def main() -> None:
    s = get_settings()
    if not (s.DATABASE_URL and s.OPENAI_API_KEY):
        sys.exit("DATABASE_URL and OPENAI_API_KEY are required")
    data = json.loads(HISTORY.read_text(encoding="utf-8"))
    try:
        pool = await db.get_pool()
        for m in data["meetings"]:
            mid = m["id"]
            await pool.execute(
                """insert into meetings (id, title, platform, meeting_url, mode, status,
                       started_at, ended_at, summary, decisions, action_items)
                   values ($1, $2, 'meet', '', 'notetaker', 'done', $3, $4, $5, $6, $7)
                   on conflict (id) do update set title = excluded.title,
                       started_at = excluded.started_at, ended_at = excluded.ended_at,
                       summary = excluded.summary, decisions = excluded.decisions,
                       action_items = excluded.action_items, status = 'done'""",
                mid,
                m["title"],
                datetime.fromisoformat(m["started_at"]),
                datetime.fromisoformat(m["ended_at"]),
                m["summary"],
                m["decisions"],
                m["action_items"],
            )
            for u in m["utterances"]:
                await db.insert_utterance(mid, u["speaker"], u["text"], u["ts_start"])
            for i, f in enumerate(m["facts"], 1):
                await pool.execute(
                    """insert into facts (id, meeting_id, speaker, text, kind)
                       values ($1, $2, $3, $4, $5) on conflict (id) do nothing""",
                    f"{mid}_f{i}",
                    mid,
                    f["speaker"],
                    f["text"],
                    f["kind"],
                )
            print(f"{mid}: {len(m['utterances'])} utterances, {len(m['facts'])} facts")
        print(f"embedded {await rag.backfill_embeddings()} rows")
    finally:
        await db.close_pool()


if __name__ == "__main__":
    asyncio.run(main())

"""Seed the MSP incident demo (profile msp): KB docs, the 6 past incident meetings, experts.

Usage: cd backend && uv run python ../scripts/seed_msp.py
Idempotent: KB docs skipped when unchanged, fixed meeting/fact ids, msp experts only when none
is tagged "profile:msp" yet (never overwrites edits made in /ui). Then embeds new rows.
Never indexes brief.md (the INC-024 ticket) or transcript_inc024.json: the current incident is
not history. Needs DATABASE_URL and OPENAI_API_KEY.
"""

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "scripts"))

from seed_history import upsert_meetings  # noqa: E402
from seed_kb import upsert_file  # noqa: E402

from app import db, escalation, rag  # noqa: E402
from app.config import get_settings  # noqa: E402

MSP = ROOT / "backend" / "seed" / "msp"
KB_FILES = (
    "runbook-wc-crm-01.md",
    "inc-011-postmortem.md",
    "slack-inc-011.md",
    "expert-directory.md",
    "client-novastore.md",
)


async def main() -> None:
    s = get_settings()
    if not (s.DATABASE_URL and s.OPENAI_API_KEY):
        sys.exit("DATABASE_URL and OPENAI_API_KEY are required")
    try:
        for name in KB_FILES:
            await upsert_file(MSP / name)
        await upsert_meetings(MSP / "history.json")
        print(f"embedded {await rag.backfill_embeddings()} rows")
        seeded = await escalation.seed_msp_experts()
        print(f"msp experts: {seeded} seeded" if seeded else "msp experts: already present")
    finally:
        await db.close_pool()


if __name__ == "__main__":
    asyncio.run(main())

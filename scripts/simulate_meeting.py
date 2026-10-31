"""Replay the 90-second demo as Recall webhooks against a local backend (no Recall, no real call).

Usage: cd backend && uv run python ../scripts/simulate_meeting.py [--base URL] [--speed 5]
                                                                   [--meeting-id ID]
Needs DATABASE_URL, WEBHOOK_TOKEN, DEMO_TOKEN in env (same values as the running backend).
Thin wrapper around backend/app/simulate.py (also behind POST /debug/simulate); adds a WS
listener and a summary.
"""

import argparse
import asyncio
import json
import sys
from collections import Counter
from pathlib import Path
from urllib.parse import quote

import websockets

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from app import db, simulate  # noqa: E402
from app.config import get_settings  # noqa: E402


async def listen(ws_url: str, events: list[dict], ready: asyncio.Event) -> None:
    async with websockets.connect(ws_url) as ws:
        ready.set()
        async for raw in ws:
            msg = json.loads(raw)
            events.append(msg)
            data = json.dumps(msg.get("data"), ensure_ascii=False)
            print(f"  <- ws {msg.get('type')}: {data[:140]}")


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8000")
    ap.add_argument("--speed", type=float, default=5.0)
    ap.add_argument("--meeting-id")
    ap.add_argument("--expert-reply", default="Thursday", help="text of the simulated expert reply")
    ap.add_argument("--no-reply", action="store_true", help="do not simulate an expert reply")
    args = ap.parse_args()

    s = get_settings()
    base = args.base.rstrip("/")
    try:
        meeting_id, bot_id = await simulate.prepare(args.meeting_id)
    except ValueError as e:
        sys.exit(str(e))
    print(f"meeting {meeting_id} bot {bot_id}")

    ws_base = base.replace("http", "ws", 1)
    ws_url = f"{ws_base}/app/ws?meeting_id={quote(meeting_id)}&token={quote(s.DEMO_TOKEN)}"
    events: list[dict] = []
    ready = asyncio.Event()
    listener = asyncio.create_task(listen(ws_url, events, ready))
    await asyncio.wait_for(ready.wait(), 10)

    sent = await simulate.drive(
        base,
        meeting_id,
        bot_id,
        speed=args.speed,
        expert_reply=None if args.no_reply else args.expert_reply,
        say=print,
    )
    await asyncio.sleep(1.5)  # let late events (agent replies etc.) arrive

    listener.cancel()
    await asyncio.gather(listener, return_exceptions=True)

    lines = simulate.load_lines()
    counts = Counter(e.get("type") for e in events)
    statuses = [e["data"].get("status") for e in events if e.get("type") == "meeting_status"]
    utterances = counts.get("utterance", 0)
    unique = len({(ln["speaker"], ln["at_s"]) for ln in lines})
    print("\n== summary ==")
    print(f"lines sent: {sent} (+1 duplicate), unique: {unique}")
    print(f"utterance events received: {utterances}")
    others = {k: v for k, v in counts.items() if k != "utterance"}
    print(
        f"escalation_created: {counts.get('escalation_created', 0)}  "
        f"escalation_answered: {counts.get('escalation_answered', 0)}"
    )
    print(f"other events: {others}  meeting_status: {statuses}")
    ok = utterances == unique
    print("RESULT:", "OK" if ok else "FAIL (utterance events != unique lines)")
    await db.close_pool()
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

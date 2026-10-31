"""Replay the 90-second demo as Recall webhooks against a local backend (no Recall, no real call).

Usage: cd backend && uv run python ../scripts/simulate_meeting.py [--base URL] [--speed 5]
                                                                   [--meeting-id ID]
Needs DATABASE_URL, WEBHOOK_TOKEN, DEMO_TOKEN in env (same values as the running backend).
"""

import argparse
import asyncio
import json
import sys
import uuid
from collections import Counter
from pathlib import Path
from urllib.parse import quote

import httpx
import websockets

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from app import db  # noqa: E402
from app.config import get_settings  # noqa: E402

FIXTURE = ROOT / "backend" / "seed" / "demo_transcript.json"
BRIEF = (
    "This week Artem finished the Slack escalation flow and the Postgres 16 tuning. "
    "He is working on the auth token cache. He cannot promise dates."
)


def payload_transcript(bot_id: str, line: dict) -> dict:
    words = line["text"].split()
    return {
        "event": "transcript.data",
        "data": {
            "data": {
                "words": [
                    {
                        "text": w,
                        "start_timestamp": {"relative": line["at_s"] + i * 0.3},
                        "end_timestamp": {"relative": line["at_s"] + i * 0.3 + 0.25},
                    }
                    for i, w in enumerate(words)
                ],
                "language_code": "en",
                "participant": {"id": 100, "name": line["speaker"], "is_host": False},
            },
            "bot": {"id": bot_id, "metadata": {}},
        },
    }


def payload_status(bot_id: str, event: str) -> dict:
    return {"event": event, "data": {"bot": {"id": bot_id}, "data": {"code": event}}}


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
    args = ap.parse_args()

    s = get_settings()
    base = args.base.rstrip("/")
    lines = json.loads(FIXTURE.read_text())

    bot_id = f"sim-{uuid.uuid4()}"
    meeting_id = args.meeting_id
    if meeting_id:
        meeting = await db.get_meeting(meeting_id)
        if not meeting or not meeting.get("recall_bot_id"):
            sys.exit("meeting not found or has no recall_bot_id")
        bot_id = meeting["recall_bot_id"]
    else:
        # HACK: bypasses Recall, inserts the meeting straight into the DB.
        m = await db.insert_meeting(
            title="Simulated stand-up",
            platform="google_meet",
            meeting_url="https://meet.google.com/sim-demo",
            mode="delegate",
            status="joining",
            started_at=None,
        )
        meeting_id = m["id"]
        await db.update_meeting(meeting_id, recall_bot_id=bot_id)
        await db.insert_brief(meeting_id, BRIEF)
    print(f"meeting {meeting_id} bot {bot_id}")

    ws_base = base.replace("http", "ws", 1)
    ws_url = f"{ws_base}/app/ws?meeting_id={quote(meeting_id)}&token={quote(s.DEMO_TOKEN)}"
    events: list[dict] = []
    ready = asyncio.Event()
    listener = asyncio.create_task(listen(ws_url, events, ready))
    await asyncio.wait_for(ready.wait(), 10)

    status_url = f"{base}/webhooks/recall/status?token={quote(s.WEBHOOK_TOKEN)}"
    tr_url = (
        f"{base}/webhooks/recall/transcript?meeting_id={quote(meeting_id)}"
        f"&token={quote(s.WEBHOOK_TOKEN)}"
    )
    sent = 0
    async with httpx.AsyncClient(timeout=10) as http:

        async def post(url: str, body: dict) -> None:
            r = await http.post(url, json=body)
            r.raise_for_status()

        for ev in ("bot.joining_call", "bot.in_call_recording"):
            print(f"-> {ev}")
            await post(status_url, payload_status(bot_id, ev))
            await asyncio.sleep(0.3)

        clock = 0.0
        for i, line in enumerate(lines):
            await asyncio.sleep(max(0.0, (line["at_s"] - clock) / args.speed))
            clock = max(clock, line["at_s"])
            print(f"-> [{line['at_s']:>3}s] {line['speaker']}: {line['text']}")
            await post(tr_url, payload_transcript(bot_id, line))
            sent += 1
            if i == 2:  # Recall retry of the same line: must be deduplicated
                print("-> (retry of the same line, expect no second utterance)")
                await post(tr_url, payload_transcript(bot_id, line))

        await asyncio.sleep(1.0)
        for ev in ("bot.call_ended", "bot.done"):
            print(f"-> {ev}")
            await post(status_url, payload_status(bot_id, ev))
            await asyncio.sleep(0.3)
        await asyncio.sleep(1.5)  # let late events (agent replies etc.) arrive

    listener.cancel()
    await asyncio.gather(listener, return_exceptions=True)

    counts = Counter(e.get("type") for e in events)
    statuses = [e["data"].get("status") for e in events if e.get("type") == "meeting_status"]
    utterances = counts.get("utterance", 0)
    unique = len({(ln["speaker"], ln["at_s"]) for ln in lines})
    print("\n== summary ==")
    print(f"lines sent: {sent} (+1 duplicate), unique: {unique}")
    print(f"utterance events received: {utterances}")
    others = {k: v for k, v in counts.items() if k != "utterance"}
    print(f"other events: {others}  meeting_status: {statuses}")
    ok = utterances == unique
    print("RESULT:", "OK" if ok else "FAIL (utterance events != unique lines)")
    await db.close_pool()
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

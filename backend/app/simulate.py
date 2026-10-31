"""HACK: replay the 90-second demo as Recall webhooks to a backend (no Recall, no real call).

`run()` (POST /debug/simulate): inserts a meeting in the DB, then a background task posts the
status + transcript webhooks to ourselves with WEBHOOK_TOKEN and answers the escalation via
/debug/expert-reply. scripts/simulate_meeting.py uses prepare() + drive() and adds a WS listener.
"""

import asyncio
import json
import logging
import os
import uuid
from collections.abc import Callable
from pathlib import Path
from urllib.parse import quote

import httpx

from app import db
from app.config import get_settings

log = logging.getLogger(__name__)

FIXTURE = Path(__file__).resolve().parent.parent / "seed" / "demo_transcript.json"
BRIEF = (
    "This week Artem finished the Slack escalation flow and the Postgres 16 tuning. "
    "He is working on the auth token cache. He cannot promise dates."
)
DEFAULT_SPEED = 20.0
DEFAULT_REPLY = "Thursday"
ESCALATION_WAIT_S = 15.0
REPLY_DELAY_S = 3.0
IDLE_WAIT_S = 20.0  # max wait for the agent to finish before the next line
OPEN_ESCALATION_S = 135.0  # no auto reply: keep the call open past the 2-min timeout

_tasks: set[asyncio.Task] = set()


async def _pause(seconds: float) -> None:
    await asyncio.sleep(seconds)  # one place, so tests can skip the waits


async def _wait_idle(meeting_id: str) -> None:
    """In-process runs only: hold the next line while the agent answers or speaks, so a
    compressed transcript (speed 20) doesn't hit the "answer in progress" drop. No-op for the
    CLI script (another process, the orchestrator there is always idle)."""
    from app import orchestrator  # lazy: orchestrator imports half the app

    for _ in range(int(IDLE_WAIT_S / 0.2)):
        if not orchestrator.is_busy(meeting_id):
            return
        await _pause(0.2)


def local_base_url() -> str:
    return f"http://127.0.0.1:{os.environ.get('PORT') or 8000}"


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


def load_lines() -> list[dict]:
    return json.loads(FIXTURE.read_text())


async def prepare(meeting_id: str | None = None) -> tuple[str, str]:
    """(meeting_id, bot_id). Reuses an existing meeting with a recall_bot_id, else inserts a
    delegate-mode meeting + brief straight into the DB (bypasses Recall)."""
    if meeting_id:
        meeting = await db.get_meeting(meeting_id)
        if not meeting or not meeting.get("recall_bot_id"):
            raise ValueError("meeting not found or has no recall_bot_id")
        return meeting_id, meeting["recall_bot_id"]
    bot_id = f"sim-{uuid.uuid4()}"
    m = await db.insert_meeting(
        title="Simulated stand-up",
        platform="google_meet",
        meeting_url="https://meet.google.com/sim-demo",
        mode="delegate",
        status="joining",
        started_at=None,
    )
    await db.update_meeting(m["id"], recall_bot_id=bot_id)
    await db.insert_brief(m["id"], BRIEF)
    return m["id"], bot_id


async def _answer_escalation(
    http: httpx.AsyncClient, base: str, meeting_id: str, reply: str | None, say
) -> None:
    q = f"token={quote(get_settings().WEBHOOK_TOKEN)}"
    waiting: list[dict] = []
    for _ in range(int(ESCALATION_WAIT_S / 0.5)):
        r = await http.get(f"{base}/debug/escalations?meeting_id={quote(meeting_id)}&{q}")
        r.raise_for_status()
        waiting = [x for x in r.json() if x["status"] == "waiting"]
        if waiting:
            break
        await _pause(0.5)
    if not waiting:
        say(f"no waiting escalation within {ESCALATION_WAIT_S:.0f} s")
        return
    if reply is None:
        # Manual reply (web app "Simulate expert reply") or timeout: keep the call live until then.
        say("no expert reply: call stays open until the escalation is answered or times out")
        for _ in range(int(OPEN_ESCALATION_S)):
            await _pause(1.0)
            r = await http.get(f"{base}/debug/escalations?meeting_id={quote(meeting_id)}&{q}")
            r.raise_for_status()
            if not any(x["status"] == "waiting" for x in r.json()):
                break
        await _pause(3.0)  # let the answer / timeout line play before the call ends
        return
    await _pause(REPLY_DELAY_S)  # let "asking Dima now" play first
    say(f"-> expert reply: {reply!r}")
    for _ in range(5):  # 409 not_delivered until the (fake) DM is stored
        r = await http.post(
            f"{base}/debug/expert-reply?{q}",
            json={"escalation_id": waiting[0]["id"], "text": reply},
        )
        if r.status_code != 409:
            r.raise_for_status()
            break
        await _pause(1.0)
    await _pause(1.5)


async def drive(
    base: str,
    meeting_id: str,
    bot_id: str,
    *,
    speed: float = DEFAULT_SPEED,
    expert_reply: str | None = DEFAULT_REPLY,
    say: Callable[[str], None] = log.info,
) -> int:
    """Post the whole call (status, transcript lines + one duplicate, expert reply, end).
    Returns the number of transcript lines sent (without the duplicate)."""
    s = get_settings()
    base = base.rstrip("/")
    lines = load_lines()
    token = quote(s.WEBHOOK_TOKEN)
    status_url = f"{base}/webhooks/recall/status?token={token}"
    tr_url = f"{base}/webhooks/recall/transcript?meeting_id={quote(meeting_id)}&token={token}"
    sent = 0
    async with httpx.AsyncClient(timeout=10) as http:

        async def post(url: str, body: dict) -> None:
            r = await http.post(url, json=body)
            r.raise_for_status()

        for ev in ("bot.joining_call", "bot.in_call_recording"):
            say(f"-> {ev}")
            await post(status_url, payload_status(bot_id, ev))
            await _pause(0.3)

        clock = 0.0
        for i, line in enumerate(lines):
            await _pause(max(0.0, (line["at_s"] - clock) / speed))
            await _wait_idle(meeting_id)
            clock = max(clock, line["at_s"])
            say(f"-> [{line['at_s']:>3}s] {line['speaker']}: {line['text']}")
            await post(tr_url, payload_transcript(bot_id, line))
            sent += 1
            if i == 2:  # Recall retry of the same line: must be deduplicated
                say("-> (retry of the same line, expect no second utterance)")
                await post(tr_url, payload_transcript(bot_id, line))

        # Escalation check (needs the LLM to say needs_expert, i.e. an OpenAI key).
        if not s.OPENAI_API_KEY:
            say("LLM not configured, skipping escalation check")
        else:
            await _answer_escalation(http, base, meeting_id, expert_reply, say)

        await _pause(1.0)
        for ev in ("bot.call_ended", "bot.done"):
            say(f"-> {ev}")
            await post(status_url, payload_status(bot_id, ev))
            await _pause(0.3)
    return sent


async def _drive_logged(base: str, meeting_id: str, bot_id: str, **kw) -> None:
    try:
        sent = await drive(base, meeting_id, bot_id, **kw)
        log.info("simulation %s done: %d lines", meeting_id, sent)
    except Exception:
        log.exception("simulation %s failed", meeting_id)


async def run(
    base_url: str | None = None,
    speed: float = DEFAULT_SPEED,
    expert_reply: str | None = DEFAULT_REPLY,
) -> str:
    """Insert the meeting, start posting webhooks in the background, return the meeting id."""
    meeting_id, bot_id = await prepare()
    task = asyncio.create_task(
        _drive_logged(
            base_url or local_base_url(),
            meeting_id,
            bot_id,
            speed=speed,
            expert_reply=expert_reply,
        )
    )
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    log.info("simulation %s started (speed %.1f)", meeting_id, speed)
    return meeting_id

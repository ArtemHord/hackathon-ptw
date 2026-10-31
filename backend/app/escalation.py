"""Slack escalation loop (SPEC "Eskalacja na Slacku", Przepływ 1-7).

start(): match expert -> escalations row (waiting) -> `escalation_created` -> background
DM via Notifier + timeout task; returns at once so the agent says "asking Dima now".
on_expert_reply(): thread reply -> first answer wins -> "Dima says: ..." in the call
(voice + Recall chat), agent_said + fact -> `escalation_answered` -> thread note.
Timeout (ESCALATION_TIMEOUT_S): spoken follow-up line + action item + `escalation_answered`
with status timeout. A late reply is still stored and published, never spoken.
"""

import asyncio
import json
import logging
import re
import secrets
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app import agent_voice, db, hub, jira, profile, recall, runtime, speech
from app.config import get_settings
from app.notifier.base import Expert, SentMessage, get_notifier

log = logging.getLogger(__name__)

SEED_PATH = Path(__file__).resolve().parent.parent / "seed" / "experts.json"
_cache: list[Expert] | None = None

ESCALATION_TIMEOUT_S = 120.0
CONTEXT_LINES = 3
LIVE_STATUSES = {"in_call", "joining"}
THANKS_LIVE = "Thanks — passed it on in the call."
THANKS_ENDED = "The call has ended — I've added it to the summary."
THANKS_LATE = "Thanks — the call moved on, I've added it to the summary."

_tasks: set[asyncio.Task] = set()
_timeouts: dict[str, asyncio.Task] = {}


def _tokens(s: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", s.lower()))


def _named(text: str, experts: list[Expert]) -> Expert | None:
    """The expert whose name is a whole word in `text` ("ask Ola" -> Ola), else None."""
    for e in experts:
        name = (e.name or "").strip()
        if name and re.search(rf"(?<![\w]){re.escape(name)}(?![\w])", text or "", re.IGNORECASE):
            return e
    return None


# "Atlas, ask Artem whether ..." -> look the person up in the Slack workspace (M10.2), so any
# teammate can be asked by name without being set up under /ui -> Experts first.
_ASK_RE = re.compile(
    r"\b(?:ask|contact|ping|message|text|dm|check with|reach out to|talk to|write to|get hold of)"
    r"[\s,]+@?([a-z][\w.'-]*(?:[\s,]+[a-z][\w.'-]*)?)",
    re.I,
)
_NOT_A_NAME = {
    "you",
    "and",
    "please",
    "to",
    "him",
    "her",
    "them",
    "the",
    "someone",
    "somebody",
    "everyone",
    "a",
    "an",
    "our",
    "my",
    "your",
    "if",
    "whether",
    "about",
    "for",
    "on",
    "slack",
    "team",
}


def requested_names(topic: str, question: str) -> list[str]:
    """Names to look up for an explicit "ask/ping/check with <name>" request, best first."""
    m = _ASK_RE.search(question or "")
    if m is None:
        return []
    out: list[str] = []
    t = (topic or "").strip()
    if t and t.lower() != "owner":
        out.append(t)
    words = [w for w in re.split(r"[\s,]+", m.group(1)) if w and w.lower() not in _NOT_A_NAME]
    if words:
        out += [" ".join(words), words[0]]
    return list(dict.fromkeys(out))


async def slack_person(topic: str, question: str) -> Expert | None:
    """The Slack workspace member asked for by name, remembered as an expert. None if the
    question is not an explicit request, Slack is not set up or nobody matches."""
    names = requested_names(topic, question)
    if not names or not runtime.get("SLACK_BOT_TOKEN"):
        return None
    from app.notifier.slack import SLACK  # lazy: keeps the import graph as before

    for name in names:
        try:
            user = await SLACK.find_user(name)
        except Exception as e:
            log.warning("slack directory lookup failed for %r: %s", name, e)
            return None
        if user:
            log.info("ask-by-name %r -> slack %s (%s)", name, user["name"], user["id"])
            try:
                return await _remember_person(user)
            except Exception:
                log.exception("could not save %s as an expert; asking anyway", user["name"])
                return Expert(
                    name=user["name"],
                    role="Slack workspace member",
                    topics=[],
                    channel="slack",
                    slack_user_id=user["id"],
                )
    log.info("ask-by-name: nobody in the workspace matches %s", names)
    return None


async def _remember_person(user: dict[str, str]) -> Expert:
    experts = await load_experts()
    for e in experts:
        if e.slack_user_id == user["id"]:
            return e
    same = next((e for e in experts if e.name.lower() == user["name"].lower()), None)
    if not get_settings().DATABASE_URL:
        return Expert(
            name=user["name"],
            role="Slack workspace member",
            topics=[],
            channel="slack",
            slack_user_id=user["id"],
        )
    if same is not None and same.id:
        await db.update_expert(same.id, slack_user_id=user["id"], channel="slack")
    else:
        tag = [] if profile.current() == "acme" else [f"{PROFILE_TAG}{profile.current()}"]
        await db.insert_expert(
            {
                "name": user["name"],
                "role": "Slack workspace member",
                "topics": tag,
                "channel": "slack",
                "slack_user_id": user["id"],
            }
        )
    from app import orchestrator  # lazy: orchestrator imports this module

    orchestrator._experts_cache = None
    for e in await load_experts(refresh=True):
        if e.slack_user_id == user["id"]:
            return e
    return Expert(
        name=user["name"],
        role="Slack workspace member",
        topics=[],
        channel="slack",
        slack_user_id=user["id"],
    )


def match_expert(topic: str, experts: list[Expert], question: str = "") -> Expert:
    """A named expert (topic first, then the question) wins; else the best token/substring
    overlap of topic vs expert topics; owner as fallback."""
    owner = next((e for e in experts if e.is_owner), None) or experts[0]
    named = _named(topic, experts) or _named(question, experts)
    if named is not None:
        return named
    topic_l = (topic or "").lower().strip()
    if not topic_l or topic_l == "owner":
        return owner
    t_tokens = _tokens(topic_l)
    best, best_score = owner, 0
    for e in experts:
        if e.is_owner:
            continue
        score = 0
        for t in e.topics:
            t = t.lower().strip()
            if not t:
                continue
            if t == topic_l:
                score += 3
            elif t in topic_l or topic_l in t:
                score += 2
            elif _tokens(t) & t_tokens:
                score += 1
        if score > best_score:
            best, best_score = e, score
    return best


# Experts per demo profile without a migration (M10): a "profile:msp" tag in topics, no tag
# = acme. The tag never leaves this module / the API layer.
PROFILE_TAG = "profile:"


def topics_profile(topics: list[str] | None) -> str:
    for t in topics or []:
        if str(t).startswith(PROFILE_TAG):
            return str(t)[len(PROFILE_TAG) :] or "acme"
    return "acme"


def strip_profile(topics: list[str] | None) -> list[str]:
    return [t for t in topics or [] if not str(t).startswith(PROFILE_TAG)]


def tag_profile(topics: list[str], name: str) -> list[str]:
    """Topics stored for an expert of profile `name` (acme stays untagged)."""
    clean = strip_profile(topics)
    return clean if name == "acme" else [*clean, f"{PROFILE_TAG}{name}"]


def _from_row(r: dict[str, Any]) -> Expert:
    fields = {k: r.get(k) for k in Expert.__dataclass_fields__ if k in r}
    fields["topics"] = strip_profile(list(r.get("topics") or []))
    fields["is_owner"] = bool(r.get("is_owner")) or "owner" in (r.get("topics") or [])
    return Expert(**fields)


def _seed_file(name: str | None = None) -> list[dict[str, Any]]:
    path = SEED_PATH if (name or profile.current()) == "acme" else profile.experts_seed_path(name)
    return json.loads(path.read_text())["experts"]


def _seed_experts(name: str | None = None) -> list[Expert]:
    return [
        Expert(**{**d, "is_owner": "owner" in d.get("topics", []) or d.get("is_owner", False)})
        for d in _seed_file(name)
    ]


async def load_experts(refresh: bool = False) -> list[Expert]:
    """Cached experts of the current demo profile from DB; HACK: falls back to the profile's
    seed file when there is no DATABASE_URL (or no expert of this profile)."""
    global _cache
    name = profile.current()  # may reset _cache when the profile changed
    if _cache is not None and not refresh:
        return _cache
    _cache = None
    if get_settings().DATABASE_URL:
        rows = await db.list_experts()
        _cache = [_from_row(r) for r in rows if topics_profile(r.get("topics")) == name]
    if not _cache:
        _cache = _seed_experts(name)
    return _cache


async def seed_experts() -> None:
    """HACK: seed/experts.json at startup, only with DATABASE_URL and no acme expert in the
    table (experts are edited in the web UI since M7.1; reseeding would overwrite edits)."""
    if not get_settings().DATABASE_URL:
        return
    try:
        rows = await db.list_experts()
        if not any(topics_profile(r.get("topics")) == "acme" for r in rows):
            await db.upsert_experts(_seed_file("acme"))
        await load_experts(refresh=True)
    except Exception as e:
        log.warning("expert seed failed: %s", e)


async def seed_msp_experts() -> int:
    """M10: seed/msp/experts.json tagged "profile:msp", only when no msp expert exists.
    Idempotent, never overwrites UI edits. Returns how many were seeded."""
    if not get_settings().DATABASE_URL:
        return 0
    try:
        rows = await db.list_experts()
        if any(topics_profile(r.get("topics")) == "msp" for r in rows):
            return 0
        path = profile.experts_seed_path("msp")
        if not path.exists():
            return 0
        items = [
            {**d, "topics": tag_profile(list(d.get("topics") or []), "msp")}
            for d in json.loads(path.read_text())["experts"]
        ]
        await db.upsert_experts(items)
        await load_experts(refresh=True)
        return len(items)
    except Exception as e:
        log.warning("msp expert seed failed: %s", e)
        return 0


def _notifier_for(channel: str):
    """HACK: without the channel's bot token, experts go to the fake notifier (offline demo)."""
    token = {"slack": "SLACK_BOT_TOKEN", "telegram": "TELEGRAM_BOT_TOKEN"}.get(channel)
    if token and not runtime.get(token):
        from app.notifier import fake  # noqa: F401  registers "fake"

        return get_notifier("fake")
    return get_notifier(channel)


def _spawn(coro) -> asyncio.Task:
    task = asyncio.create_task(coro)
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    return task


async def _try(coro, what: str, default: Any = None) -> Any:
    try:
        return await coro
    except Exception as e:
        log.warning("escalation: %s failed: %s", what, e)
        return default


def _int(v: Any) -> int | None:
    return None if v is None else int(round(float(v)))


def public(row: dict[str, Any], expert: str | None = None) -> dict[str, Any]:
    """The escalation object of docs/API.pl.md (WS events and GET /meetings/{id})."""
    return {
        "id": row["id"],
        "expert": row.get("expert") or expert or "the expert",
        "channel": row.get("channel") or "slack",
        "question": row["question"],
        "asked_by": row.get("asked_by"),
        "ts": _int(row.get("ts")) or 0,
        "status": row["status"],
        "answer": row.get("answer"),
        "answered_ts": _int(row.get("answered_ts")),
    }


def _elapsed_s(since: datetime | None) -> float:
    if since is None:
        return 0.0
    if since.tzinfo is None:
        since = since.replace(tzinfo=UTC)
    return max(0.0, (datetime.now(UTC) - since).total_seconds())


async def _orb(coro) -> None:
    """Orb visuals are best effort: bounded, never raises, never blocks the voice path."""
    try:
        await asyncio.wait_for(coro, 0.3)
    except Exception as e:
        log.info("orb signal failed: %s", e.__class__.__name__)


async def start(meeting_id: str, question: str, topic: str, asked_by: str) -> dict[str, Any] | None:
    """Orchestrator hook. Returns {"expert", "escalation_id"} before any Slack I/O; None if the
    escalation could not be recorded. Never raises."""
    try:
        expert = await slack_person(topic, question) or match_expert(
            topic, await load_experts(), question
        )
        meeting, recent = await asyncio.gather(
            _try(db.get_meeting(meeting_id), "get_meeting"),
            _try(db.get_last_utterances(meeting_id, CONTEXT_LINES), "get_last_utterances", []),
        )
        meeting = meeting or {}
        # Same clock as the transcript: the question utterance was stored just before us.
        ts = float(recent[-1]["ts_start"]) if recent else _elapsed_s(meeting.get("started_at"))
        row = await db.insert_escalation(
            meeting_id=meeting_id,
            expert_id=expert.id,
            channel=expert.channel,
            question=question,
            asked_by=asked_by,
            ts=ts,
        )
    except Exception:
        log.exception("escalation start failed in %s", meeting_id)
        return None
    esc_id = row["id"]
    await _try(
        hub.publish(meeting_id, "escalation_created", public(row, expert.name)), "publish created"
    )
    await _orb(
        agent_voice.send_ask(meeting_id, esc_id, question, expert.name, ESCALATION_TIMEOUT_S)
    )
    context = [f"{u['speaker']}: {u['text']}" for u in recent][-CONTEXT_LINES:]
    _spawn(_deliver(esc_id, expert, meeting.get("title") or "", asked_by, question, context))
    _timeouts[esc_id] = _spawn(_timeout(meeting_id, esc_id, expert.name, question))
    log.info("escalation %s: %r -> %s (%s)", esc_id, question, expert.name, expert.channel)
    return {"expert": expert.name, "escalation_id": esc_id}


async def _deliver(
    esc_id: str,
    expert: Expert,
    meeting_title: str,
    asked_by: str,
    question: str,
    context: list[str],
) -> None:
    """DM the expert and remember the thread. On failure the escalation stays waiting."""
    try:
        notifier = _notifier_for(expert.channel)
        if notifier is None:
            log.warning("escalation %s: no notifier for channel %r", esc_id, expert.channel)
            return
        sent = await notifier.send_question(
            expert,
            meeting_title=meeting_title or "Call",
            asked_by=asked_by,
            question=question,
            context_lines=context,
        )
        await db.set_escalation_external(esc_id, sent.external_msg_id, sent.external_channel_id)
    except Exception as e:
        log.warning("escalation %s: notifying %s failed: %s", esc_id, expert.name, e)


async def _speak(meeting_id: str, text: str, esc_id: str, ts: float, chat: bool, bot_id) -> None:
    """Voice + (optional) Recall chat + agent_said row/event. Each step best effort."""
    await _try(speech.say(meeting_id, text), "say")
    if chat:
        await _try(recall.send_chat_message(bot_id, text), "recall chat")
    said = await _try(db.insert_agent_said(meeting_id, text, ts, esc_id), "insert agent_said")
    if said:
        await _try(
            hub.publish(
                meeting_id,
                "agent_said",
                {"id": said["id"], "text": text, "ts": _int(ts), "in_reply_to": esc_id},
            ),
            "publish agent_said",
        )


async def _timeout(meeting_id: str, esc_id: str, expert: str, question: str) -> None:
    try:
        await asyncio.sleep(ESCALATION_TIMEOUT_S)
        row = await db.timeout_escalation(esc_id)
        if row is None:
            return  # answered in time
        name = row.get("expert") or expert
        await _orb(agent_voice.send_ask_done(meeting_id, esc_id, "timeout"))
        meeting = await _try(db.get_meeting(meeting_id), "get_meeting") or {}
        if meeting.get("status") in LIVE_STATUSES:
            ts = float(row.get("ts") or 0) + _elapsed_s(row.get("asked_at"))
            line = f"{name} hasn't answered yet — I've added it to follow-ups."
            await _speak(meeting_id, line, esc_id, ts, False, None)
        item: dict[str, Any] = {"owner": name, "text": question, "due": None}
        follow_up = jira.configured() and bool(jira.project_key())
        if follow_up:
            item = {"id": f"ai_{secrets.token_hex(4)}", **item}
        await _try(db.append_action_item(meeting_id, item), "append action item")
        if follow_up:  # M7.4: Jira follow-up in the background, the spoken line is already out
            jira.spawn(
                jira.followup_for_timeout(
                    meeting_id, item["id"], question, str(row.get("asked_by") or "someone"), name
                )
            )
        await _try(
            hub.publish(meeting_id, "escalation_answered", public(row, name)), "publish timeout"
        )
        log.info("escalation %s timed out (%s)", esc_id, name)
    except asyncio.CancelledError:
        pass
    except Exception:
        log.exception("escalation %s timeout handling failed", esc_id)
    finally:
        _timeouts.pop(esc_id, None)


async def on_expert_reply(channel_id: str, thread_ts: str, text: str, user_id: str) -> None:
    """Slack thread reply from an expert. Only the first reply counts. Never raises."""
    try:
        await _on_reply(channel_id, thread_ts, (text or "").strip(), user_id)
    except Exception:
        log.exception("expert reply handling failed (thread %s)", thread_ts)


async def on_expert_dm(channel_id: str, text: str, user_id: str) -> None:
    """A plain DM (not in the thread), e.g. typed on a phone: answers the open question that
    was sent to this DM channel. Never raises."""
    try:
        esc = await db.get_open_escalation_by_channel(channel_id)
        if esc is None or not esc.get("external_msg_id"):
            log.info("DM in %s without an open question ignored", channel_id)
            return
        await _on_reply(channel_id, esc["external_msg_id"], (text or "").strip(), user_id)
    except Exception:
        log.exception("expert DM handling failed (%s)", channel_id)


async def _on_reply(channel_id: str, thread_ts: str, text: str, user_id: str) -> None:
    if not text:
        return
    esc = await db.get_escalation_by_external(thread_ts, channel_id)
    if esc is None:
        log.info("reply in unknown thread %s/%s ignored", channel_id, thread_ts)
        return
    if esc["status"] == "answered":
        log.info("escalation %s already answered, extra reply from %s ignored", esc["id"], user_id)
        return
    esc_id, meeting_id = esc["id"], esc["meeting_id"]
    answered_ts = float(esc.get("ts") or 0) + _elapsed_s(esc.get("asked_at"))
    row = await db.answer_escalation(esc_id, text, answered_ts)
    if row is None:
        return  # lost a race with another reply
    late = row.get("prev_status") == "timeout"
    if not late:
        task = _timeouts.pop(esc_id, None)
        if task is not None and task is not asyncio.current_task():
            task.cancel()
    expert = row.get("expert") or esc.get("expert") or "The expert"
    meeting = await _try(db.get_meeting(meeting_id), "get_meeting") or {}
    live = meeting.get("status") in LIVE_STATUSES
    if live and not late:
        await _orb(agent_voice.send_ask_done(meeting_id, esc_id, "answered"))
        line = f"{expert} says: {text}"
        await _speak(meeting_id, line, esc_id, answered_ts, True, meeting.get("recall_bot_id"))
        await _try(
            db.insert_fact(meeting_id, expert, f"Q: {row['question']}\nA: {text}", "answer"),
            "insert fact",
        )
        try:  # make the fresh fact searchable by /chat right away
            from app import rag

            rag.backfill_later()
        except Exception:
            log.exception("backfill_later failed")
    await _try(
        hub.publish(meeting_id, "escalation_answered", public(row, expert)), "publish answered"
    )
    notifier = _notifier_for(row.get("channel") or "slack")
    if notifier is not None:
        note = THANKS_LIVE if live and not late else (THANKS_LATE if live else THANKS_ENDED)
        sent = SentMessage(
            channel=row.get("channel") or "slack",
            external_msg_id=row.get("external_msg_id") or thread_ts,
            external_channel_id=row.get("external_channel_id") or channel_id,
        )
        await _try(notifier.post_reply(sent, note), "thread reply")
    log.info("escalation %s answered by %s (late=%s, live=%s)", esc_id, expert, late, live)

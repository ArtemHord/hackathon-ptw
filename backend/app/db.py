"""asyncpg pool (lazy) + query helpers. The app boots and /health works without DATABASE_URL."""

import json
import logging
import ssl
from contextlib import asynccontextmanager
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import asyncpg
from fastapi import FastAPI

from app.config import get_settings

log = logging.getLogger(__name__)

_pool: asyncpg.Pool | None = None

MEETING_COLUMNS = (
    "id, owner_id, title, platform, meeting_url, recall_bot_id, mode, status, "
    "started_at, ended_at, summary, decisions, action_items, created_at"
)
MEETING_UPDATABLE = {
    "title",
    "platform",
    "meeting_url",
    "recall_bot_id",
    "mode",
    "status",
    "started_at",
    "ended_at",
    "summary",
}


def _split_ssl(url: str) -> tuple[str, Any]:
    """Return (url without sslmode, ssl arg for asyncpg). Same logic as scripts/migrate.py."""
    parts = urlsplit(url)
    query = parse_qsl(parts.query)
    mode = next((v for k, v in query if k == "sslmode"), None)
    rest = [(k, v) for k, v in query if k != "sslmode"]
    clean = urlunsplit(parts._replace(query=urlencode(rest)))
    if mode in (None, "disable", "allow", "prefer"):
        return clean, (False if mode in ("disable", "allow") else None)
    ctx = ssl.create_default_context()
    if mode in ("require", "verify-ca"):
        # HACK: Supabase pooler cert chain; encrypt without verification for require.
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    return clean, ctx


async def _init_conn(conn: asyncpg.Connection) -> None:
    """jsonb/json <-> Python objects (decisions, action_items, citations)."""
    for typ in ("jsonb", "json"):
        await conn.set_type_codec(typ, encoder=json.dumps, decoder=json.loads, schema="pg_catalog")


async def get_pool() -> asyncpg.Pool:
    """Create the pool on first use. Raises RuntimeError when DATABASE_URL is empty."""
    global _pool
    if _pool is None:
        url = get_settings().DATABASE_URL
        if not url:
            raise RuntimeError("DATABASE_URL is not set")
        clean, ssl_arg = _split_ssl(url)
        kwargs: dict[str, Any] = {
            "statement_cache_size": 0,
            "min_size": 1,
            "max_size": 5,
            "init": _init_conn,
        }
        if ssl_arg is not None:
            kwargs["ssl"] = ssl_arg
        _pool = await asyncpg.create_pool(clean, **kwargs)
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    if get_settings().DATABASE_URL:
        try:
            await get_pool()
        except Exception as e:  # keep booting; get_pool retries on first query
            log.warning("DB pool init failed: %s", e)
    yield
    await close_pool()


# --- meetings / briefs -------------------------------------------------------


async def insert_meeting(
    *,
    title: str,
    platform: str,
    meeting_url: str,
    mode: str,
    status: str,
    started_at: Any,
) -> dict[str, Any]:
    pool = await get_pool()
    row = await pool.fetchrow(
        f"""insert into meetings (title, platform, meeting_url, mode, status, started_at)
            values ($1, $2, $3, $4, $5, $6) returning {MEETING_COLUMNS}""",
        title,
        platform,
        meeting_url,
        mode,
        status,
        started_at,
    )
    return dict(row)


async def get_meeting(meeting_id: str) -> dict[str, Any] | None:
    pool = await get_pool()
    row = await pool.fetchrow(f"select {MEETING_COLUMNS} from meetings where id = $1", meeting_id)
    return dict(row) if row else None


async def get_meeting_by_bot(bot_id: str) -> dict[str, Any] | None:
    pool = await get_pool()
    row = await pool.fetchrow(
        f"select {MEETING_COLUMNS} from meetings where recall_bot_id = $1", bot_id
    )
    return dict(row) if row else None


async def update_meeting(meeting_id: str, **fields: Any) -> dict[str, Any] | None:
    bad = set(fields) - MEETING_UPDATABLE
    if bad:
        raise ValueError(f"not updatable: {sorted(bad)}")
    if not fields:
        return await get_meeting(meeting_id)
    names = list(fields)
    sets = ", ".join(f"{n} = ${i + 2}" for i, n in enumerate(names))
    pool = await get_pool()
    row = await pool.fetchrow(
        f"update meetings set {sets} where id = $1 returning {MEETING_COLUMNS}",
        meeting_id,
        *(fields[n] for n in names),
    )
    return dict(row) if row else None


async def insert_brief(meeting_id: str, text: str) -> None:
    pool = await get_pool()
    await pool.execute("insert into briefs (meeting_id, text) values ($1, $2)", meeting_id, text)


# --- utterances --------------------------------------------------------------


async def insert_utterance(
    meeting_id: str,
    speaker: str,
    text: str,
    ts_start: float,
    ts_end: float | None = None,
) -> dict[str, Any] | None:
    """Insert one transcript line. Returns the row, or None when it already exists (retry)."""
    pool = await get_pool()
    row = await pool.fetchrow(
        """insert into utterances (meeting_id, speaker, text, ts_start, ts_end)
           values ($1, $2, $3, $4, $5)
           on conflict (meeting_id, speaker, ts_start) do nothing
           returning id, meeting_id, speaker, text, ts_start, ts_end""",
        meeting_id,
        speaker,
        text,
        ts_start,
        ts_end,
    )
    return dict(row) if row else None


async def get_meeting_mode(meeting_id: str) -> str | None:
    pool = await get_pool()
    return await pool.fetchval("select mode from meetings where id = $1", meeting_id)


async def get_brief(meeting_id: str) -> str:
    """Latest brief text for the meeting, "" when there is none."""
    pool = await get_pool()
    text = await pool.fetchval(
        "select text from briefs where meeting_id = $1 order by created_at desc limit 1",
        meeting_id,
    )
    return text or ""


async def get_recent_utterances(
    meeting_id: str, since_ts: float, limit: int = 200
) -> list[dict[str, Any]]:
    """Utterances with ts_start >= since_ts (seconds from call start), oldest first."""
    pool = await get_pool()
    rows = await pool.fetch(
        """select * from (
             select id, speaker, text, ts_start from utterances
             where meeting_id = $1 and ts_start >= $2
             order by ts_start desc limit $3
           ) t order by ts_start""",
        meeting_id,
        since_ts,
        limit,
    )
    return [dict(r) for r in rows]


# --- agent_said --------------------------------------------------------------


async def insert_agent_said(
    meeting_id: str, text: str, ts: float | None, in_reply_to: str | None = None
) -> dict[str, Any]:
    pool = await get_pool()
    row = await pool.fetchrow(
        """insert into agent_said (meeting_id, text, ts, in_reply_to)
           values ($1, $2, $3, $4) returning id, meeting_id, text, ts, in_reply_to""",
        meeting_id,
        text,
        ts,
        in_reply_to,
    )
    return dict(row)


# --- experts -----------------------------------------------------------------


async def upsert_experts(experts: list[dict[str, Any]]) -> None:
    """Idempotent by name. No is_owner column: owner = topics contain "owner"."""
    pool = await get_pool()
    for e in experts:
        topics = list(e.get("topics") or [])
        if e.get("is_owner") and "owner" not in topics:
            topics.append("owner")
        args = (
            e.get("role"),
            topics,
            e.get("channel") or "slack",
            e.get("email"),
            e.get("slack_user_id"),
            e.get("telegram_chat_id"),
            e["name"],
        )
        status = await pool.execute(
            """update experts set role=$1, topics=$2, channel=$3, email=$4,
               slack_user_id=coalesce($5, slack_user_id),
               telegram_chat_id=coalesce($6, telegram_chat_id) where name=$7""",
            *args,
        )
        if status.endswith(" 0"):
            await pool.execute(
                """insert into experts (role, topics, channel, email, slack_user_id,
                   telegram_chat_id, name) values ($1,$2,$3,$4,$5,$6,$7)""",
                *args,
            )


async def list_experts() -> list[dict[str, Any]]:
    pool = await get_pool()
    rows = await pool.fetch(
        """select id, name, coalesce(role,'') as role, topics, channel, email,
           slack_user_id, telegram_chat_id, ('owner' = any(topics)) as is_owner
           from experts order by created_at, name"""
    )
    return [dict(r) for r in rows]


async def get_last_utterances(meeting_id: str, n: int = 3) -> list[dict[str, Any]]:
    """Last n utterances of the meeting, oldest first."""
    pool = await get_pool()
    rows = await pool.fetch(
        """select * from (
             select id, speaker, text, ts_start from utterances
             where meeting_id = $1 order by ts_start desc limit $2
           ) t order by ts_start""",
        meeting_id,
        n,
    )
    return [dict(r) for r in rows]


async def append_action_item(meeting_id: str, item: dict[str, Any]) -> None:
    pool = await get_pool()
    await pool.execute(
        """update meetings set action_items = coalesce(action_items, '[]'::jsonb) || $2::jsonb
           where id = $1""",
        meeting_id,
        [item],
    )


# --- facts -------------------------------------------------------------------


async def insert_fact(meeting_id: str, speaker: str, text: str, kind: str) -> dict[str, Any]:
    pool = await get_pool()
    row = await pool.fetchrow(
        """insert into facts (meeting_id, speaker, text, kind) values ($1, $2, $3, $4)
           returning id, meeting_id, speaker, text, kind""",
        meeting_id,
        speaker,
        text,
        kind,
    )
    return dict(row)


# --- escalations -------------------------------------------------------------

ESCALATION_COLUMNS = (
    "e.id, e.meeting_id, e.expert_id, x.name as expert, e.channel, e.question, e.asked_by, "
    "e.ts, e.external_msg_id, e.external_channel_id, e.answer, e.status, e.asked_at, "
    "e.answered_at, e.answered_ts"
)


async def insert_escalation(
    *,
    meeting_id: str,
    expert_id: str | None,
    channel: str,
    question: str,
    asked_by: str,
    ts: float,
) -> dict[str, Any]:
    pool = await get_pool()
    row = await pool.fetchrow(
        f"""with e as (
              insert into escalations (meeting_id, expert_id, channel, question, asked_by, ts)
              values ($1, $2, $3, $4, $5, $6) returning *
            )
            select {ESCALATION_COLUMNS} from e left join experts x on x.id = e.expert_id""",
        meeting_id,
        expert_id,
        channel,
        question,
        asked_by,
        ts,
    )
    return dict(row)


async def set_escalation_external(
    escalation_id: str, external_msg_id: str, external_channel_id: str
) -> None:
    pool = await get_pool()
    await pool.execute(
        "update escalations set external_msg_id = $2, external_channel_id = $3 where id = $1",
        escalation_id,
        external_msg_id,
        external_channel_id,
    )


async def get_escalation_by_external(
    external_msg_id: str, external_channel_id: str | None = None
) -> dict[str, Any] | None:
    pool = await get_pool()
    row = await pool.fetchrow(
        f"""select {ESCALATION_COLUMNS} from escalations e
            left join experts x on x.id = e.expert_id
            where e.external_msg_id = $1
              and ($2::text is null or e.external_channel_id is null
                   or e.external_channel_id = $2)
            order by e.created_at desc limit 1""",
        external_msg_id,
        external_channel_id,
    )
    return dict(row) if row else None


async def answer_escalation(
    escalation_id: str, answer: str, answered_ts: float
) -> dict[str, Any] | None:
    """First answer wins: sets status answered unless already answered. The row carries
    prev_status ('waiting' | 'timeout'); None when it was already answered or unknown."""
    pool = await get_pool()
    row = await pool.fetchrow(
        f"""with prev as (
              select id, status from escalations where id = $1 for update
            ), e as (
              update escalations u set answer = $2, answered_ts = $3, answered_at = now(),
                     status = 'answered'
              from prev where u.id = prev.id and prev.status <> 'answered'
              returning u.*, prev.status as prev_status
            )
            select {ESCALATION_COLUMNS}, e.prev_status
            from e left join experts x on x.id = e.expert_id""",
        escalation_id,
        answer,
        answered_ts,
    )
    return dict(row) if row else None


async def timeout_escalation(escalation_id: str) -> dict[str, Any] | None:
    """waiting -> timeout. None when it is no longer waiting (answered in time)."""
    pool = await get_pool()
    row = await pool.fetchrow(
        f"""with e as (
              update escalations set status = 'timeout'
              where id = $1 and status = 'waiting' returning *
            )
            select {ESCALATION_COLUMNS} from e left join experts x on x.id = e.expert_id""",
        escalation_id,
    )
    return dict(row) if row else None


async def get_escalation(escalation_id: str) -> dict[str, Any] | None:
    pool = await get_pool()
    try:
        row = await pool.fetchrow(
            f"""select {ESCALATION_COLUMNS} from escalations e
                left join experts x on x.id = e.expert_id where e.id = $1""",
            escalation_id,
        )
    except asyncpg.DataError:  # not a uuid
        return None
    return dict(row) if row else None


async def list_escalations(meeting_id: str | None = None) -> list[dict[str, Any]]:
    pool = await get_pool()
    rows = await pool.fetch(
        f"""select {ESCALATION_COLUMNS} from escalations e
            left join experts x on x.id = e.expert_id
            where ($1::text is null or e.meeting_id::text = $1)
            order by e.created_at desc limit 50""",
        meeting_id,
    )
    return [dict(r) for r in rows]

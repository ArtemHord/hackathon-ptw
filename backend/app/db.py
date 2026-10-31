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

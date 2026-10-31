"""asyncpg pool (lazy) + query helpers. The app boots and /health works without DATABASE_URL."""

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


async def get_pool() -> asyncpg.Pool:
    """Create the pool on first use. Raises RuntimeError when DATABASE_URL is empty."""
    global _pool
    if _pool is None:
        url = get_settings().DATABASE_URL
        if not url:
            raise RuntimeError("DATABASE_URL is not set")
        clean, ssl_arg = _split_ssl(url)
        kwargs: dict[str, Any] = {"statement_cache_size": 0, "min_size": 1, "max_size": 5}
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

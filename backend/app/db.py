"""asyncpg pool (lazy) + query helpers. The app boots and /health works without DATABASE_URL."""

import asyncio
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
    "decisions",
    "action_items",
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


async def get_all_utterances(meeting_id: str) -> list[dict[str, Any]]:
    """Full transcript, oldest first (post-call summary)."""
    pool = await get_pool()
    rows = await pool.fetch(
        "select speaker, text, ts_start from utterances where meeting_id = $1 "
        "order by ts_start, created_at",
        meeting_id,
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


# --- read helpers for GET /meetings, GET /meetings/{id} ---------------------


async def list_meetings(limit: int = 100) -> list[dict[str, Any]]:
    pool = await get_pool()
    rows = await pool.fetch(
        f"""select {MEETING_COLUMNS} from meetings
            order by coalesce(started_at, created_at) desc, created_at desc limit $1""",
        limit,
    )
    return [dict(r) for r in rows]


async def get_meeting_detail(meeting_id: str, since: int | None = None) -> dict[str, Any] | None:
    """Meeting row + the per-table lists of docs/API.pl.md. With `since`: only ts > since;
    escalations also when answered_ts > since or when they ended in timeout (no change time)."""
    m = await get_meeting(meeting_id)
    if m is None:
        return None
    pool = await get_pool()
    s = None if since is None else float(since)
    utt, fcs, escs, said = await asyncio.gather(
        pool.fetch(
            """select id, speaker, text, ts_start as ts from utterances
               where meeting_id = $1 and ($2::float8 is null or ts_start > $2)
               order by ts_start, created_at""",
            meeting_id,
            s,
        ),
        pool.fetch(
            """select f.id, f.claim, f.verdict, d.title as source, f.correction, f.ts,
                      f.proposal_id
               from fact_checks f
               left join kb_chunks c on c.id = f.kb_chunk_id
               left join kb_docs d on d.id = c.doc_id
               where f.meeting_id = $1 and ($2::float8 is null or f.ts > $2)
               order by f.ts, f.created_at""",
            meeting_id,
            s,
        ),
        pool.fetch(
            f"""select {ESCALATION_COLUMNS} from escalations e
                left join experts x on x.id = e.expert_id
                where e.meeting_id = $1
                  and ($2::float8 is null or e.ts > $2 or e.answered_ts > $2
                       or e.status = 'timeout')
                order by e.ts, e.created_at""",
            meeting_id,
            s,
        ),
        pool.fetch(
            """select id, text, ts, in_reply_to from agent_said
               where meeting_id = $1 and ($2::float8 is null or ts > $2)
               order by ts, created_at""",
            meeting_id,
            s,
        ),
    )
    return {
        "meeting": m,
        "utterances": [dict(r) for r in utt],
        "fact_checks": [dict(r) for r in fcs],
        "escalations": [dict(r) for r in escs],
        "agent_said": [dict(r) for r in said],
    }


# --- knowledge base / vector search ------------------------------------------


def vec_literal(v: list[float]) -> str:
    """pgvector text form; cast with ::vector in SQL (no codec needed)."""
    return "[" + ",".join(repr(float(x)) for x in v) + "]"


async def list_kb_docs() -> list[dict[str, Any]]:
    pool = await get_pool()
    rows = await pool.fetch(
        """select d.id, d.title, d.version, d.updated_at, d.created_at,
                  (select count(*) from kb_chunks c where c.doc_id = d.id) as chunks
           from kb_docs d order by d.created_at, d.title"""
    )
    return [dict(r) for r in rows]


async def kb_doc_by_title(title: str) -> dict[str, Any] | None:
    pool = await get_pool()
    row = await pool.fetchrow(
        "select id, title, version, updated_at, created_at from kb_docs where title = $1", title
    )
    return dict(row) if row else None


async def upsert_kb_doc(title: str, chunks: list[str], embeddings: list[list[float]]) -> dict:
    """New doc -> version 1; existing title -> version + 1 and all its chunks replaced."""
    pool = await get_pool()
    async with pool.acquire() as conn, conn.transaction():
        row = await conn.fetchrow(
            "select id, version from kb_docs where title = $1 for update", title
        )
        if row:
            doc_id, version = row["id"], row["version"] + 1
            await conn.execute("delete from kb_chunks where doc_id = $1", doc_id)
            await conn.execute(
                "update kb_docs set version = $2, updated_at = now() where id = $1",
                doc_id,
                version,
            )
        else:
            version = 1
            doc_id = await conn.fetchval(
                "insert into kb_docs (title, version) values ($1, 1) returning id", title
            )
        await conn.executemany(
            "insert into kb_chunks (doc_id, text, embedding, version) "
            "values ($1, $2, $3::vector, $4)",
            [(doc_id, t, vec_literal(e), version) for t, e in zip(chunks, embeddings, strict=True)],
        )
        d = await conn.fetchrow(
            "select id, title, version, updated_at from kb_docs where id = $1", doc_id
        )
    return {**dict(d), "chunks": len(chunks)}


async def vector_search(qvec: list[float], k: int, kinds: tuple[str, ...]) -> list[dict[str, Any]]:
    """Cosine search (<=>) over kb_chunks / facts / utterances that have embeddings."""
    parts: list[str] = []
    if "kb" in kinds:
        parts.append(
            """(select 'kb' as kind, c.text, d.title as doc_title, null::text as meeting_id,
                      null::real as ts, null::text as speaker,
                      1 - (c.embedding <=> $1::vector) as score
               from kb_chunks c join kb_docs d on d.id = c.doc_id
               where c.embedding is not null order by c.embedding <=> $1::vector limit $2)"""
        )
    if "facts" in kinds:
        parts.append(
            """(select 'facts', f.text, null, f.meeting_id, null::real, f.speaker,
                      1 - (f.embedding <=> $1::vector)
               from facts f where f.embedding is not null
               order by f.embedding <=> $1::vector limit $2)"""
        )
    if "utterances" in kinds:
        parts.append(
            """(select 'utterances', u.text, null, u.meeting_id, u.ts_start, u.speaker,
                      1 - (u.embedding <=> $1::vector)
               from utterances u where u.embedding is not null
               order by u.embedding <=> $1::vector limit $2)"""
        )
    if not parts:
        return []
    pool = await get_pool()
    rows = await pool.fetch(
        "select * from (" + " union all ".join(parts) + ") x order by score desc limit $2",
        vec_literal(qvec),
        k,
    )
    return [dict(r) for r in rows]


async def rows_without_embedding(table: str, limit: int) -> list[dict[str, Any]]:
    if table not in ("facts", "utterances"):
        raise ValueError(table)
    pool = await get_pool()
    rows = await pool.fetch(
        f"select id, text from {table} where embedding is null order by created_at limit $1",
        limit,
    )
    return [dict(r) for r in rows]


async def set_embeddings(table: str, items: list[tuple[str, list[float]]]) -> None:
    if table not in ("facts", "utterances"):
        raise ValueError(table)
    pool = await get_pool()
    await pool.executemany(
        f"update {table} set embedding = $2::vector where id = $1",
        [(i, vec_literal(v)) for i, v in items],
    )


# --- chat --------------------------------------------------------------------


async def insert_chat_message(role: str, text: str, citations: list[dict[str, Any]]) -> None:
    pool = await get_pool()
    await pool.execute(
        "insert into chat_messages (role, text, citations) values ($1, $2, $3::jsonb)",
        role,
        text,
        json.dumps(citations),
    )


async def answered_ts_for_expert(meeting_id: str, expert_name: str) -> int | None:
    """Latest answered_ts of an answered escalation by this expert in the meeting."""
    pool = await get_pool()
    v = await pool.fetchval(
        """select e.answered_ts from escalations e join experts x on x.id = e.expert_id
           where e.meeting_id::text = $1 and x.name = $2 and e.status = 'answered'
             and e.answered_ts is not null
           order by e.answered_ts desc limit 1""",
        meeting_id,
        expert_name,
    )
    return int(v) if v is not None else None


# --- fact checks -------------------------------------------------------------


async def insert_fact_check(
    meeting_id: str,
    *,
    utterance_id: str | None,
    claim: str,
    verdict: str,
    confidence: float | None,
    correction: str | None,
    posted: bool,
    ts: float | None,
    kb_chunk_id: str | None = None,
) -> dict[str, Any]:
    pool = await get_pool()
    row = await pool.fetchrow(
        """insert into fact_checks
             (meeting_id, utterance_id, claim, verdict, kb_chunk_id, confidence, correction,
              posted, ts)
           values ($1, $2, $3, $4, $5, $6, $7, $8, $9)
           returning id, meeting_id, claim, verdict, correction, posted, ts""",
        meeting_id,
        utterance_id,
        claim,
        verdict,
        kb_chunk_id,
        confidence,
        correction,
        posted,
        ts,
    )
    return dict(row)


async def kb_chunk_for_title(title: str) -> str | None:
    """A chunk id of the doc whose title matches, ignoring case and a trailing .md."""
    pool = await get_pool()
    row = await pool.fetchrow(
        """select c.id from kb_chunks c join kb_docs d on d.id = c.doc_id
           where regexp_replace(lower(d.title), '\\.md$', '')
               = regexp_replace(lower($1), '\\.md$', '')
           limit 1""",
        title.strip(),
    )
    return row["id"] if row else None

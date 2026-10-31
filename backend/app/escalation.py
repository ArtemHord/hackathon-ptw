"""Slack escalation: expert matching (M3.1). M3.3 extends this with the full loop."""

import json
import logging
import re
from pathlib import Path

from app import db
from app.config import get_settings
from app.notifier.base import Expert

log = logging.getLogger(__name__)

SEED_PATH = Path(__file__).resolve().parent.parent / "seed" / "experts.json"
_cache: list[Expert] | None = None


def _tokens(s: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", s.lower()))


def match_expert(topic: str, experts: list[Expert]) -> Expert:
    """Best expert by token/substring overlap of topic vs expert topics; owner as fallback."""
    owner = next((e for e in experts if e.is_owner), None) or experts[0]
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


def _seed_experts() -> list[Expert]:
    data = json.loads(SEED_PATH.read_text())["experts"]
    return [
        Expert(**{**d, "is_owner": "owner" in d.get("topics", []) or d.get("is_owner", False)})
        for d in data
    ]


async def load_experts(refresh: bool = False) -> list[Expert]:
    """Cached experts from DB; HACK: falls back to seed file when no DATABASE_URL."""
    global _cache
    if _cache is not None and not refresh:
        return _cache
    if get_settings().DATABASE_URL:
        _cache = [Expert(**r) for r in await db.list_experts()]
    if not _cache:
        _cache = _seed_experts()
    return _cache


async def seed_experts() -> None:
    """HACK: upsert seed/experts.json at startup, only when DATABASE_URL is set."""
    if not get_settings().DATABASE_URL:
        return
    try:
        await db.upsert_experts(json.loads(SEED_PATH.read_text())["experts"])
        await load_experts(refresh=True)
    except Exception as e:
        log.warning("expert seed failed: %s", e)


async def on_expert_reply(channel_id: str, thread_ts: str, text: str, user_id: str) -> None:
    """Slack thread reply from an expert. Stub: M3.3 finds the escalation by thread_ts."""
    log.info(
        "expert reply in %s thread %s from %s (%d chars)", channel_id, thread_ts, user_id, len(text)
    )

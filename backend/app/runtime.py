"""Runtime settings editable from the web UI (M7.1): DB table app_settings over env.

`get(key)` = non-empty DB override, else the env value from `get_settings()`. Overrides are
loaded once at startup (`load()`) and kept in memory; `save()` writes the DB first, then
memory. Without DATABASE_URL nothing touches the DB (save only updates memory: tests, offline).
HACK: secrets are stored as plaintext (single demo user, endpoints behind DEMO_TOKEN).
"""

import logging

from app import db
from app.config import get_settings

log = logging.getLogger(__name__)

EDITABLE = (
    "AGENT_NAME",
    "OWNER_NAME",
    "SLACK_BOT_TOKEN",
    "SLACK_SIGNING_SECRET",
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_WEBHOOK_SECRET",
    "JIRA_BASE_URL",
    "JIRA_EMAIL",
    "JIRA_API_TOKEN",
    "JIRA_PROJECT_KEY",
    "JIRA_AUTO_CREATE",
)
SECRETS = frozenset(
    {
        "SLACK_BOT_TOKEN",
        "SLACK_SIGNING_SECRET",
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_WEBHOOK_SECRET",
        "JIRA_API_TOKEN",
    }
)
TRUTHY = {"1", "true", "yes", "on"}

_overrides: dict[str, str] = {}


def _env(key: str) -> str:
    return str(getattr(get_settings(), key, "") or "")


def get(key: str) -> str:
    """Override if set, else env (pydantic default included)."""
    return _overrides.get(key) or _env(key)


def get_bool(key: str) -> bool:
    return get(key).strip().lower() in TRUTHY


def source(key: str) -> str:
    """Where the value comes from: "db", "env" or "unset"."""
    if _overrides.get(key):
        return "db"
    return "env" if _env(key) else "unset"


async def load() -> None:
    """Read app_settings into memory. Never raises (boot must not fail on a missing table)."""
    if not get_settings().DATABASE_URL:
        return
    try:
        rows = await db.list_settings()
    except Exception as e:
        log.warning("runtime settings load failed (env only): %s", e)
        return
    _overrides.clear()
    _overrides.update({k: v for k, v in rows.items() if k in EDITABLE and v})


async def save(updates: dict[str, str]) -> None:
    """Partial update. "" deletes the override (back to env). Unknown key -> KeyError."""
    unknown = [k for k in updates if k not in EDITABLE]
    if unknown:
        raise KeyError(", ".join(unknown))
    clean = {k: (v or "").strip() for k, v in updates.items()}
    if get_settings().DATABASE_URL:
        for key, value in clean.items():
            if value:
                await db.upsert_setting(key, value)
            else:
                await db.delete_setting(key)
    for key, value in clean.items():
        if value:
            _overrides[key] = value
        else:
            _overrides.pop(key, None)


def reset() -> None:
    """Tests: drop every in-memory override."""
    _overrides.clear()

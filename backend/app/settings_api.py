"""Web UI setup endpoints (M7.1): runtime settings, integrations, experts CRUD.

All behind `Authorization: Bearer DEMO_TOKEN`; errors in the API.pl.md shape.
"""

import logging
import re
from typing import Any, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, field_validator

from app import db, escalation, jira, orchestrator, runtime, telegram_api
from app.config import get_settings
from app.meetings import ApiError, require_demo_token
from app.notifier.base import Expert, NotifierError
from app.notifier.slack import SLACK

log = logging.getLogger(__name__)

router = APIRouter(dependencies=[Depends(require_demo_token)])

OWNER_TOPIC = "owner"


# --- settings -------------------------------------------------------------------


def _entry(key: str) -> dict[str, Any]:
    secret = key in runtime.SECRETS
    value = runtime.get(key)
    return {
        "secret": secret,
        "value": None if secret else value,
        "set": bool(value),
        "hint": f"…{value[-4:]}" if secret and value else None,
        "source": runtime.source(key),
    }


def _settings() -> dict[str, Any]:
    return {
        "values": {k: _entry(k) for k in runtime.EDITABLE},
        "public_base_url": get_settings().PUBLIC_BASE_URL,
    }


@router.get("/settings")
async def get_settings_view() -> dict[str, Any]:
    return _settings()


@router.put("/settings")
async def put_settings(body: dict[str, str]) -> dict[str, Any]:
    unknown = sorted(k for k in body if k not in runtime.EDITABLE)
    if unknown:
        raise ApiError(422, "validation_error", f"Unknown setting: {', '.join(unknown)}")
    await runtime.save(body)
    if {"SLACK_BOT_TOKEN"} & body.keys():
        SLACK.reset()  # cached bot user id / email lookups belong to the old workspace
    if {"TELEGRAM_BOT_TOKEN"} & body.keys():
        telegram_api.reset()
    return _settings()


# --- integrations -----------------------------------------------------------------


def _public(path: str) -> str:
    return f"{get_settings().PUBLIC_BASE_URL.rstrip('/')}{path}"


@router.get("/integrations")
async def integrations() -> dict[str, Any]:
    return {
        "slack": {
            "configured": bool(
                runtime.get("SLACK_BOT_TOKEN") and runtime.get("SLACK_SIGNING_SECRET")
            ),
            "webhook_url": _public("/webhooks/slack"),
        },
        "telegram": {
            "configured": telegram_api.configured(),
            "webhook_url": _public("/webhooks/telegram"),
            "bot_username": telegram_api.bot_username(),
        },
        "jira": {
            "configured": jira.configured(),
            "base_url": jira.base_url() or None,
            "project_key": runtime.get("JIRA_PROJECT_KEY") or None,
        },
    }


async def _test_slack() -> dict[str, Any]:
    if not runtime.get("SLACK_BOT_TOKEN"):
        return {"ok": False, "detail": "Slack bot token is not set"}
    try:
        data = await SLACK.auth_test()
    except NotifierError as e:
        return {"ok": False, "detail": str(e)}
    who = data.get("user") or data.get("user_id") or "the bot"
    team = data.get("team") or "the workspace"
    detail = f"Connected to {team} as {who}"
    if not runtime.get("SLACK_SIGNING_SECRET"):
        detail += "; signing secret is not set, replies will be rejected"
    return {"ok": True, "detail": detail}


async def _test_telegram() -> dict[str, Any]:
    if not telegram_api.configured():
        return {"ok": False, "detail": "Telegram bot token is not set", "bot_username": None}
    try:
        me = await telegram_api.get_me()
    except telegram_api.TelegramError as e:
        return {"ok": False, "detail": str(e), "bot_username": None}
    username = me.get("username")
    base = get_settings().PUBLIC_BASE_URL
    secret = runtime.get("TELEGRAM_WEBHOOK_SECRET")
    if not base:
        return {
            "ok": False,
            "detail": f"Bot @{username} reachable, but PUBLIC_BASE_URL is not set: "
            "webhook not registered",
            "bot_username": username,
        }
    if not secret or not re.fullmatch(r"[A-Za-z0-9_-]{1,256}", secret):
        why = "is not set" if not secret else "may only contain A-Z a-z 0-9 _ - (1-256 chars)"
        return {
            "ok": False,
            "detail": f"Bot @{username} reachable, but the webhook secret {why}: "
            "webhook not registered",
            "bot_username": username,
        }
    try:
        await telegram_api.set_webhook(_public("/webhooks/telegram"), secret)
    except telegram_api.TelegramError as e:
        return {"ok": False, "detail": str(e), "bot_username": username}
    return {
        "ok": True,
        "detail": f"Bot @{username} connected, webhook set to {_public('/webhooks/telegram')}",
        "bot_username": username,
    }


async def _test_jira() -> dict[str, Any]:
    if not jira.configured():
        return {"ok": False, "detail": "Jira base URL, email and API token are required"}
    try:
        me = await jira.myself()
    except jira.JiraError as e:
        return {"ok": False, "detail": str(e)}
    who = me.get("displayName") or me.get("emailAddress") or "unknown user"
    return {"ok": True, "detail": f"Connected to {jira.base_url()} as {who}"}


TESTS = {"slack": _test_slack, "telegram": _test_telegram, "jira": _test_jira}


@router.post("/integrations/{name}/test")
async def test_integration(name: str) -> dict[str, Any]:
    test = TESTS.get(name)
    if test is None:
        raise ApiError(404, "not_found", f"Unknown integration {name}")
    return await test()


# --- experts ------------------------------------------------------------------------


class ExpertIn(BaseModel):
    name: str
    role: str = ""
    topics: list[str] = []
    channel: Literal["slack", "telegram"] = "slack"
    email: str | None = None
    slack_user_id: str | None = None
    telegram_chat_id: str | None = None
    is_owner: bool = False

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("must not be empty")
        return v.strip()


class ExpertPatch(BaseModel):
    name: str | None = None
    role: str | None = None
    topics: list[str] | None = None
    channel: Literal["slack", "telegram"] | None = None
    email: str | None = None
    slack_user_id: str | None = None
    telegram_chat_id: str | None = None
    is_owner: bool | None = None

    @field_validator("name")
    @classmethod
    def _name(cls, v: str | None) -> str | None:
        if v is not None and not v.strip():
            raise ValueError("must not be empty")
        return v.strip() if v is not None else None


def _clean_topics(topics: list[str]) -> list[str]:
    out: list[str] = []
    for t in topics:
        t = t.strip()
        if t and t.lower() != OWNER_TOPIC and t not in out:
            out.append(t)
    return out


def _db_topics(topics: list[str], is_owner: bool) -> list[str]:
    """No is_owner column: the owner is the expert with "owner" in topics (db.upsert_experts)."""
    return [*_clean_topics(topics), *([OWNER_TOPIC] if is_owner else [])]


def _opt(v: str | None) -> str | None:
    return (v or "").strip() or None


def _public_expert(e: dict[str, Any] | Expert) -> dict[str, Any]:
    d = e.__dict__ if isinstance(e, Expert) else e
    topics = list(d.get("topics") or [])
    return {
        "id": d.get("id"),
        "name": d.get("name") or "",
        "role": d.get("role") or "",
        "topics": _clean_topics(topics),
        "channel": d.get("channel") or "slack",
        "email": d.get("email"),
        "slack_user_id": d.get("slack_user_id"),
        "telegram_chat_id": d.get("telegram_chat_id"),
        "is_owner": bool(d.get("is_owner")) or OWNER_TOPIC in topics,
    }


def _require_db() -> None:
    if not get_settings().DATABASE_URL:
        raise ApiError(409, "conflict", "Editing experts needs a database")


async def _invalidate() -> None:
    """Escalation and the agent prompt must see the edit at once."""
    orchestrator._experts_cache = None  # noqa: SLF001
    try:
        await escalation.load_experts(refresh=True)
    except Exception as e:
        log.warning("experts reload failed: %s", e)


async def _get_or_404(expert_id: str) -> dict[str, Any]:
    _require_db()
    row = await db.get_expert(expert_id)
    if row is None:
        raise ApiError(404, "not_found", f"Expert {expert_id} not found")
    return row


@router.get("/experts")
async def list_experts() -> dict[str, Any]:
    if get_settings().DATABASE_URL:
        rows: list[Any] = await db.list_experts()
    else:
        rows = await escalation.load_experts()  # HACK: seed file, read-only
    return {"items": [_public_expert(r) for r in rows]}


@router.post("/experts", status_code=201)
async def create_expert(body: ExpertIn) -> dict[str, Any]:
    _require_db()
    row = await db.insert_expert(
        {
            "name": body.name,
            "role": body.role.strip(),
            "topics": _db_topics(body.topics, body.is_owner),
            "channel": body.channel,
            "email": _opt(body.email),
            "slack_user_id": _opt(body.slack_user_id),
            "telegram_chat_id": _opt(body.telegram_chat_id),
        }
    )
    await _invalidate()
    return _public_expert(row)


@router.put("/experts/{expert_id}")
async def update_expert(expert_id: str, body: ExpertPatch) -> dict[str, Any]:
    current = await _get_or_404(expert_id)
    patch = body.model_dump(exclude_unset=True)
    fields: dict[str, Any] = {}
    for k in ("name", "channel"):
        if patch.get(k) is not None:
            fields[k] = patch[k]
    if "role" in patch:
        fields["role"] = (patch["role"] or "").strip()
    for k in ("email", "slack_user_id", "telegram_chat_id"):
        if k in patch:
            fields[k] = _opt(patch[k])
    if "topics" in patch or "is_owner" in patch:
        topics = patch.get("topics")
        is_owner = patch.get("is_owner")
        fields["topics"] = _db_topics(
            current.get("topics") or [] if topics is None else topics,
            bool(current.get("is_owner")) if is_owner is None else is_owner,
        )
    row = await db.update_expert(expert_id, **fields)
    if row is None:
        raise ApiError(404, "not_found", f"Expert {expert_id} not found")
    await _invalidate()
    return _public_expert(row)


@router.delete("/experts/{expert_id}")
async def delete_expert(expert_id: str) -> dict[str, Any]:
    _require_db()
    if not await db.delete_expert(expert_id):
        raise ApiError(404, "not_found", f"Expert {expert_id} not found")
    await _invalidate()
    return {"id": expert_id, "deleted": True}


def _test_text(name: str) -> str:
    agent, owner = runtime.get("AGENT_NAME"), runtime.get("OWNER_NAME")
    return (
        f"Hi {name}, this is a test message from Call Crew. When {agent}, {owner}'s AI "
        "delegate, needs your help during a call, the question will arrive here and your "
        "reply will be read out in the call."
    )


@router.post("/experts/{expert_id}/test")
async def test_expert(expert_id: str) -> dict[str, Any]:
    row = await _get_or_404(expert_id)
    expert = Expert(**row)
    notifier = escalation._notifier_for(expert.channel)  # noqa: SLF001
    if notifier is None:
        return {"ok": False, "detail": f"{expert.channel} is not available yet"}
    try:
        sent = await notifier.send_text(expert, _test_text(expert.name))
    except Exception as e:
        return {"ok": False, "detail": str(e) or e.__class__.__name__}
    if sent.channel == "fake":
        return {
            "ok": False,
            "detail": f"{expert.channel} is not configured: message only logged (fake notifier)",
        }
    return {"ok": True, "detail": f"Test message sent to {expert.name} via {expert.channel}"}

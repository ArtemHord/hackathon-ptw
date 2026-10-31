"""Slack adapter: DM an expert a question, post thread notes. Registers itself as "slack".

Web API (docs.slack.dev/reference/methods): users.lookupByEmail (GET ?email=) -> user.id,
conversations.open {users} -> channel.id, chat.postMessage {channel, text, thread_ts?} -> ts,
auth.test -> user_id. Errors come back as HTTP 200 with {"ok": false, "error": "..."}.
"""

import difflib
import logging
import re
import time
from typing import Any

import httpx

from app import runtime
from app.notifier.base import Expert, NotifierError, SentMessage, register_notifier

__all__ = ["SLACK", "NotifierError", "SlackNotifier", "format_question"]

log = logging.getLogger(__name__)

SLACK_API = "https://slack.com/api"
TIMEOUT_S = 10.0
CONTEXT_LINES = 3
MEMBERS_TTL_S = 120.0
NAME_MATCH_MIN = 0.8  # "Artem", "Julian Pulawski", "Mikhail" (-> mikhailtroian), ASR typos


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def name_score(query: str, field: str) -> float:
    """0..1 how well a spoken name matches a Slack name field (real, display or user name)."""
    qn, fn = _norm(query), _norm(field)
    if not qn or not fn:
        return 0.0
    if qn == fn:
        return 1.0
    q_tok = re.findall(r"[a-z0-9]+", query.lower())
    f_tok = re.findall(r"[a-z0-9]+", field.lower())
    if q_tok and all(any(f.startswith(q) for f in f_tok) for q in q_tok):
        return 0.95  # "artem" -> "Artem Hordiienko"
    if len(qn) >= 4 and fn.startswith(qn):
        return 0.9  # "mikhail" -> "mikhailtroian"
    return difflib.SequenceMatcher(None, qn, fn).ratio()  # "juliana pulawski", "mikhailtoian"


def _esc(s: str) -> str:
    """Slack mrkdwn control characters (docs.slack.dev 'Escaping text')."""
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _quote(s: str) -> str:
    return "\n".join(f"> {line}" for line in (_esc(s).splitlines() or [""]))


def format_question(
    *, meeting_title: str, asked_by: str, question: str, context_lines: list[str]
) -> str:
    parts = [
        f'*Call Crew* — question from the call "{_esc(meeting_title)}"',
        f"Asked by *{_esc(asked_by)}*:",
        _quote(question),
    ]
    ctx = [c for c in context_lines if c and c.strip()][-CONTEXT_LINES:]
    if ctx:
        parts.append("_Recent context:_\n" + "\n".join(f"• {_esc(c)}" for c in ctx))
    parts.append("Reply here (or in this thread) and I'll read it out in the call.")
    return "\n".join(parts)


class SlackNotifier:
    def __init__(self) -> None:
        self._email_cache: dict[str, str] = {}
        self._bot_user_id: str | None = None
        self._members: list[dict[str, Any]] = []
        self._members_at = 0.0

    def reset(self) -> None:
        self._email_cache.clear()
        self._bot_user_id = None
        self._members = []
        self._members_at = 0.0

    async def members(self) -> list[dict[str, Any]]:
        """Human workspace members (users.list, needs users:read), cached for a few minutes."""
        if not self._members or time.monotonic() - self._members_at > MEMBERS_TTL_S:
            data = await self._call("users.list", params={"limit": 500})
            self._members = [
                m
                for m in data.get("members") or []
                if not m.get("is_bot") and not m.get("deleted") and m.get("id") != "USLACKBOT"
            ]
            self._members_at = time.monotonic()
        return self._members

    async def find_user(self, name: str) -> dict[str, str] | None:
        """{"id", "name"} of the workspace member a spoken name refers to, else None."""
        best, best_score = None, 0.0
        for m in await self.members():
            p = m.get("profile") or {}
            fields = [p.get("real_name"), p.get("display_name"), m.get("real_name"), m.get("name")]
            score = max((name_score(name, f) for f in fields if f), default=0.0)
            if score > best_score:
                best, best_score = m, score
        if best is None or best_score < NAME_MATCH_MIN:
            return None
        p = best.get("profile") or {}
        label = p.get("real_name") or p.get("display_name") or best.get("name") or best["id"]
        return {"id": best["id"], "name": label}

    async def _call(
        self, method: str, *, json: dict[str, Any] | None = None, params: dict | None = None
    ) -> dict[str, Any]:
        token = runtime.get("SLACK_BOT_TOKEN")
        if not token:
            raise NotifierError("SLACK_BOT_TOKEN is not set")
        headers = {"Authorization": f"Bearer {token}"}
        try:
            async with httpx.AsyncClient(base_url=SLACK_API, timeout=TIMEOUT_S) as client:
                if params is not None:
                    r = await client.get(f"/{method}", params=params, headers=headers)
                else:
                    r = await client.post(f"/{method}", json=json or {}, headers=headers)
            r.raise_for_status()
            data = r.json()
        except (httpx.HTTPError, ValueError) as e:
            raise NotifierError(f"slack {method} failed: {e}") from e
        if not isinstance(data, dict) or not data.get("ok"):
            err = data.get("error") if isinstance(data, dict) else "bad response"
            raise NotifierError(f"slack {method}: {err}")
        return data

    async def auth_test(self) -> dict[str, Any]:
        """auth.test: {user_id, user, team, ...}; raises NotifierError (integration test)."""
        data = await self._call("auth.test")
        self._bot_user_id = data.get("user_id") or self._bot_user_id
        return data

    async def bot_user_id(self) -> str | None:
        """Our bot's user id from auth.test, cached; None if Slack is unreachable."""
        if self._bot_user_id is None:
            try:
                self._bot_user_id = (await self._call("auth.test")).get("user_id")
            except NotifierError as e:
                log.warning("auth.test failed: %s", e)
        return self._bot_user_id

    async def resolve_user(self, expert: Expert) -> str:
        if expert.slack_user_id:
            return expert.slack_user_id
        if not expert.email:
            raise NotifierError(f"expert {expert.name} has no slack_user_id or email")
        key = expert.email.lower()
        if key not in self._email_cache:
            data = await self._call("users.lookupByEmail", params={"email": expert.email})
            uid = (data.get("user") or {}).get("id")
            if not uid:
                raise NotifierError(f"users.lookupByEmail: no user id for {expert.name}")
            self._email_cache[key] = uid
        return self._email_cache[key]

    async def send_question(
        self,
        expert: Expert,
        *,
        meeting_title: str,
        asked_by: str,
        question: str,
        context_lines: list[str],
    ) -> SentMessage:
        text = format_question(
            meeting_title=meeting_title,
            asked_by=asked_by,
            question=question,
            context_lines=context_lines,
        )
        return await self._dm(expert, text, mention=True)

    async def send_text(self, expert: Expert, text: str) -> SentMessage:
        return await self._dm(expert, text)

    async def _dm(self, expert: Expert, text: str, mention: bool = False) -> SentMessage:
        user_id = await self.resolve_user(expert)
        if mention:
            text = f"<@{user_id}> {text}"  # tagged, so it reads as addressed to them
        opened = await self._call("conversations.open", json={"users": user_id})
        channel = (opened.get("channel") or {}).get("id")
        if not channel:
            raise NotifierError("conversations.open: no channel id")
        posted = await self._call("chat.postMessage", json={"channel": channel, "text": text})
        ts = posted.get("ts")
        if not ts:
            raise NotifierError("chat.postMessage: no ts")
        return SentMessage(
            channel="slack", external_msg_id=ts, external_channel_id=posted.get("channel", channel)
        )

    async def post_reply(self, sent: SentMessage, text: str) -> None:
        await self._call(
            "chat.postMessage",
            json={
                "channel": sent.external_channel_id,
                "thread_ts": sent.external_msg_id,
                "text": text,
            },
        )


SLACK = SlackNotifier()
register_notifier("slack", SLACK)

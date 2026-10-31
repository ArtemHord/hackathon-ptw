"""Slack adapter: DM an expert a question, post thread notes. Registers itself as "slack".

Web API (docs.slack.dev/reference/methods): users.lookupByEmail (GET ?email=) -> user.id,
conversations.open {users} -> channel.id, chat.postMessage {channel, text, thread_ts?} -> ts,
auth.test -> user_id. Errors come back as HTTP 200 with {"ok": false, "error": "..."}.
"""

import logging
from typing import Any

import httpx

from app.config import get_settings
from app.notifier.base import Expert, SentMessage, register_notifier

log = logging.getLogger(__name__)

SLACK_API = "https://slack.com/api"
TIMEOUT_S = 10.0
CONTEXT_LINES = 3


class NotifierError(RuntimeError):
    """A notifier could not deliver (HTTP error, ok:false, unknown expert)."""


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
    parts.append("Reply in this thread and I'll read it out in the call.")
    return "\n".join(parts)


class SlackNotifier:
    def __init__(self) -> None:
        self._email_cache: dict[str, str] = {}
        self._bot_user_id: str | None = None

    def reset(self) -> None:
        self._email_cache.clear()
        self._bot_user_id = None

    async def _call(
        self, method: str, *, json: dict[str, Any] | None = None, params: dict | None = None
    ) -> dict[str, Any]:
        token = get_settings().SLACK_BOT_TOKEN
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
        user_id = await self.resolve_user(expert)
        opened = await self._call("conversations.open", json={"users": user_id})
        channel = (opened.get("channel") or {}).get("id")
        if not channel:
            raise NotifierError("conversations.open: no channel id")
        text = format_question(
            meeting_title=meeting_title,
            asked_by=asked_by,
            question=question,
            context_lines=context_lines,
        )
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

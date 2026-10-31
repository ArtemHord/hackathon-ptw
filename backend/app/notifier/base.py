"""Channel-agnostic notifier interface. Adapters (slack, telegram) register themselves on import."""

from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class Expert:
    name: str
    role: str = ""
    topics: list[str] = field(default_factory=list)
    channel: str = "slack"
    email: str | None = None
    slack_user_id: str | None = None
    telegram_chat_id: str | None = None
    is_owner: bool = False
    id: str | None = None


@dataclass
class SentMessage:
    channel: str
    external_msg_id: str
    external_channel_id: str


class Notifier(Protocol):
    async def send_question(
        self,
        expert: Expert,
        *,
        meeting_title: str,
        asked_by: str,
        question: str,
        context_lines: list[str],
    ) -> SentMessage: ...

    async def post_reply(self, sent: SentMessage, text: str) -> None:
        """Thread note, e.g. "Thanks, passed it on"."""
        ...


NOTIFIERS: dict[str, Notifier] = {}


def register_notifier(channel: str, notifier: Notifier) -> None:
    NOTIFIERS[channel] = notifier


def get_notifier(channel: str) -> Notifier | None:
    return NOTIFIERS.get(channel)

"""HACK: fake notifier for running the escalation loop without Slack (verifier, stage backup)."""

import logging
import uuid

from app.notifier.base import Expert, SentMessage, register_notifier

log = logging.getLogger(__name__)


class FakeNotifier:
    async def send_question(
        self,
        expert: Expert,
        *,
        meeting_title: str,
        asked_by: str,
        question: str,
        context_lines: list[str],
    ) -> SentMessage:
        log.info("FAKE DM to %s: %s", expert.name, question)
        return SentMessage(
            channel="fake", external_msg_id=f"fake-{uuid.uuid4()}", external_channel_id="fake"
        )

    async def post_reply(self, sent: SentMessage, text: str) -> None:
        log.info("FAKE thread reply (%s): %s", sent.external_msg_id, text)

    async def send_text(self, expert: Expert, text: str) -> SentMessage:
        log.info("FAKE DM to %s: %s", expert.name, text)
        return SentMessage(
            channel="fake", external_msg_id=f"fake-{uuid.uuid4()}", external_channel_id="fake"
        )


FAKE = FakeNotifier()
register_notifier("fake", FAKE)

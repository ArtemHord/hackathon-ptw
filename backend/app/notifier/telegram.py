"""Telegram adapter: message an expert in their private chat with the bot. Registers as "telegram".

sendMessage {chat_id, text, reply_markup: {force_reply, input_field_placeholder}} -> Message.
post_reply uses `reply_parameters` (the old `reply_to_message_id` is deprecated). Plain text
(no parse_mode), so user content never needs escaping. The expert's chat id comes from the
`/start <expert_id>` deep link handled in webhooks_telegram.
"""

from app import telegram_api
from app.notifier.base import Expert, NotifierError, SentMessage, register_notifier

__all__ = ["TELEGRAM", "NotifierError", "TelegramNotifier", "format_question"]

CONTEXT_LINES = 3
MAX_LEN = 4000  # Telegram limit is 4096 chars


def format_question(
    *, meeting_title: str, asked_by: str, question: str, context_lines: list[str]
) -> str:
    parts = [
        f'Call Crew: question from the call "{meeting_title}"',
        f"Asked by {asked_by}:",
        question,
    ]
    ctx = [c for c in context_lines if c and c.strip()][-CONTEXT_LINES:]
    if ctx:
        parts.append("Recent context:\n" + "\n".join(f"- {c}" for c in ctx))
    parts.append("Reply to this message with your answer and I'll read it out in the call.")
    return "\n\n".join(parts)[:MAX_LEN]


class TelegramNotifier:
    async def _send(self, chat_id: str, text: str, **extra) -> SentMessage:
        try:
            msg = await telegram_api.send_message(chat_id, text[:MAX_LEN], **extra)
        except telegram_api.TelegramError as e:
            raise NotifierError(str(e)) from None
        mid = msg.get("message_id")
        if mid is None:
            raise NotifierError("telegram sendMessage: no message_id")
        return SentMessage("telegram", str(mid), str((msg.get("chat") or {}).get("id", chat_id)))

    def _chat(self, expert: Expert) -> str:
        if not expert.telegram_chat_id:
            raise NotifierError(
                f"{expert.name} has not linked Telegram: ask them to open the bot's deep link"
            )
        return expert.telegram_chat_id

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
        return await self._send(
            self._chat(expert),
            text,
            reply_markup={"force_reply": True, "input_field_placeholder": "Your answer"},
        )

    async def send_text(self, expert: Expert, text: str) -> SentMessage:
        return await self._send(self._chat(expert), text)

    async def post_reply(self, sent: SentMessage, text: str) -> None:
        await self._send(
            sent.external_channel_id,
            text,
            reply_parameters={"message_id": int(sent.external_msg_id)},
        )


TELEGRAM = TelegramNotifier()
register_notifier("telegram", TELEGRAM)

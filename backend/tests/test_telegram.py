import asyncio
import json

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from app import db, escalation, orchestrator, telegram_api, webhooks_telegram
from app.config import get_settings
from app.main import app
from app.notifier.base import Expert, NotifierError, SentMessage, get_notifier

TG = "https://api.telegram.org/bot123:tg-token"
SECRET = "hook_secret-1"
URL = "/webhooks/telegram"
HDR_NAME = "X-Telegram-Bot-Api-Secret-Token"
HDR = {HDR_NAME: SECRET}


@pytest.fixture(autouse=True)
def env(monkeypatch):
    for k, v in {
        "DATABASE_URL": "",
        "TELEGRAM_BOT_TOKEN": "123:tg-token",
        "TELEGRAM_WEBHOOK_SECRET": SECRET,
        "AGENT_NAME": "Atlas",
    }.items():
        monkeypatch.setenv(k, v)
    get_settings.cache_clear()
    telegram_api.reset()
    webhooks_telegram.reset()
    yield
    get_settings.cache_clear()
    webhooks_telegram.reset()


def sent_ok(mid=77, chat=555):
    return httpx.Response(
        200, json={"ok": True, "result": {"message_id": mid, "chat": {"id": chat}}}
    )


def update(uid, text, *, reply_to=None, is_bot=False, chat=555, user=555):
    msg = {"message_id": uid + 1000, "from": {"id": user, "is_bot": is_bot}, "chat": {"id": chat}}
    msg["text"] = text
    if reply_to is not None:
        msg["reply_to_message"] = {"message_id": reply_to}
    return {"update_id": uid, "message": msg}


# ---------- adapter ----------


@respx.mock
async def test_send_question_payload():
    route = respx.post(f"{TG}/sendMessage").mock(return_value=sent_ok())
    expert = Expert(name="Dima", channel="telegram", telegram_chat_id="555")
    sent = await get_notifier("telegram").send_question(
        expert,
        meeting_title="Q3 sync",
        asked_by="Anna",
        question="When is the Postgres 17 upgrade?",
        context_lines=["a: one", "b: two"],
    )
    assert sent == SentMessage("telegram", "77", "555")
    body = json.loads(route.calls.last.request.content)
    assert body["chat_id"] == "555"
    assert body["reply_markup"] == {"force_reply": True, "input_field_placeholder": "Your answer"}
    for part in ("Q3 sync", "Anna", "Postgres 17", "- b: two", "Reply to this message"):
        assert part in body["text"]


@respx.mock
async def test_post_reply_uses_reply_parameters():
    route = respx.post(f"{TG}/sendMessage").mock(return_value=sent_ok(78))
    await get_notifier("telegram").post_reply(SentMessage("telegram", "77", "555"), "Thanks")
    body = json.loads(route.calls.last.request.content)
    assert body["reply_parameters"] == {"message_id": 77}
    assert "reply_to_message_id" not in body and body["chat_id"] == "555"


async def test_missing_chat_id_tells_to_open_deep_link():
    with pytest.raises(NotifierError, match="deep link"):
        await get_notifier("telegram").send_text(Expert(name="Dima", channel="telegram"), "hi")


@respx.mock
async def test_api_error_becomes_notifier_error_without_token():
    respx.post(f"{TG}/sendMessage").mock(
        return_value=httpx.Response(403, json={"ok": False, "description": "bot was blocked"})
    )
    with pytest.raises(NotifierError, match="bot was blocked") as ei:
        await get_notifier("telegram").send_text(
            Expert(name="D", channel="telegram", telegram_chat_id="1"), "hi"
        )
    assert "tg-token" not in str(ei.value)


def test_notifier_for_falls_back_to_fake_without_token(monkeypatch):
    assert escalation._notifier_for("telegram").__class__.__name__ == "TelegramNotifier"
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "")
    get_settings.cache_clear()
    assert escalation._notifier_for("telegram").__class__.__name__ != "TelegramNotifier"


# ---------- webhook ----------


def test_secret_missing_or_wrong_is_401(monkeypatch):
    with TestClient(app) as c:
        assert c.post(URL, json=update(1, "x")).status_code == 401
        assert c.post(URL, json=update(1, "x"), headers={HDR_NAME: "nope"}).status_code == 401
        monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "")
        get_settings.cache_clear()
        assert c.post(URL, json=update(1, "x"), headers=HDR).status_code == 401  # fail closed


@pytest.fixture
def replies(monkeypatch):
    calls = []

    async def on_reply(*args):
        calls.append(args)

    monkeypatch.setattr(escalation, "on_expert_reply", on_reply)
    return calls


async def post(payload, headers=HDR):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        r = await c.post(URL, json=payload, headers=headers)
    if webhooks_telegram._tasks:
        await asyncio.gather(*list(webhooks_telegram._tasks))
    return r


async def test_reply_goes_to_escalation(replies):
    r = await post(update(2, "Thursday", reply_to=77, chat=555, user=999))
    assert r.status_code == 200 and r.json() == {"ok": True}
    assert replies == [("555", "77", "Thursday", "999")]


async def test_dedup_and_bots_and_plain_messages(replies):
    await post(update(3, "Thursday", reply_to=77))
    await post(update(3, "Thursday", reply_to=77))  # Telegram retry
    await post(update(4, "bot talk", reply_to=77, is_bot=True))
    await post(update(5, "hello, no reply"))
    assert len(replies) == 1


async def test_start_links_expert(monkeypatch):
    updated = {}

    async def get_expert(eid):
        return {"id": eid, "name": "Dima"} if eid == "ex_dima" else None

    async def update_expert(eid, **f):
        updated[eid] = f

    async def load(refresh=False):
        updated["refreshed"] = refresh

    monkeypatch.setattr(db, "get_expert", get_expert)
    monkeypatch.setattr(db, "update_expert", update_expert)
    monkeypatch.setattr(escalation, "load_experts", load)
    orchestrator._experts_cache = ["stale"]
    with respx.mock:
        route = respx.post(f"{TG}/sendMessage").mock(return_value=sent_ok())
        await post(update(6, "/start ex_dima", chat=555))
        await post(update(7, "/start nobody", chat=556))
    assert updated == {"ex_dima": {"telegram_chat_id": "555"}, "refreshed": True}
    assert orchestrator._experts_cache is None
    texts = [json.loads(c.request.content)["text"] for c in route.calls]
    assert texts == ["Linked: you'll get questions from Atlas here.", "Unknown link"]

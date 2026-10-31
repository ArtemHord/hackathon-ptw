import hashlib
import hmac
import json
import time

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from app import escalation, webhooks_slack
from app.config import get_settings
from app.main import app
from app.notifier.base import Expert, SentMessage, get_notifier
from app.notifier.slack import SLACK, NotifierError

API = "https://slack.com/api"
SECRET = "test-signing-secret"
URL = "/webhooks/slack"


@pytest.fixture(autouse=True)
def env(monkeypatch):
    for k, v in {
        "WEBHOOK_TOKEN": "wh-t",
        "DEMO_TOKEN": "demo-t",
        "DATABASE_URL": "",
        "SLACK_BOT_TOKEN": "xoxb-test",
        "SLACK_SIGNING_SECRET": SECRET,
    }.items():
        monkeypatch.setenv(k, v)
    get_settings.cache_clear()
    SLACK.reset()
    webhooks_slack.reset()
    yield
    get_settings.cache_clear()
    SLACK.reset()
    webhooks_slack.reset()


def ok(**kw):
    return httpx.Response(200, json={"ok": True, **kw})


# ---------- adapter ----------


@respx.mock
async def test_send_question_chain_and_text():
    lookup = respx.get(f"{API}/users.lookupByEmail").mock(return_value=ok(user={"id": "U_DIMA"}))
    opened = respx.post(f"{API}/conversations.open").mock(return_value=ok(channel={"id": "D1"}))
    post = respx.post(f"{API}/chat.postMessage").mock(
        return_value=ok(channel="D1", ts="1700000000.000100")
    )
    expert = Expert(name="Dima", email="dima@example.com")
    sent = await get_notifier("slack").send_question(
        expert,
        meeting_title="Q3 <infra> sync",
        asked_by="Anna",
        question="What is the Postgres 17 upgrade date?",
        context_lines=["a: one", "b: two", "c: three", "d: four"],
    )
    assert sent == SentMessage("slack", "1700000000.000100", "D1")

    req = lookup.calls[0].request
    assert req.url.params["email"] == "dima@example.com"
    assert req.headers["Authorization"] == "Bearer xoxb-test"
    assert json.loads(opened.calls[0].request.content) == {"users": "U_DIMA"}
    body = json.loads(post.calls[0].request.content)
    assert body["channel"] == "D1" and "thread_ts" not in body
    text = body["text"]
    assert text.startswith('*Call Crew* — question from the call "Q3 &lt;infra&gt; sync"')
    assert "Anna" in text
    assert "> What is the Postgres 17 upgrade date?" in text
    assert "a: one" not in text and all(x in text for x in ("b: two", "c: three", "d: four"))
    assert text.endswith("Reply in this thread and I'll read it out in the call.")


@respx.mock
async def test_slack_user_id_skips_lookup_and_email_cached():
    lookup = respx.get(f"{API}/users.lookupByEmail").mock(return_value=ok(user={"id": "U1"}))
    respx.post(f"{API}/conversations.open").mock(return_value=ok(channel={"id": "D1"}))
    respx.post(f"{API}/chat.postMessage").mock(return_value=ok(channel="D1", ts="1.1"))
    kw = dict(meeting_title="t", asked_by="a", question="q", context_lines=[])

    await SLACK.send_question(Expert(name="X", slack_user_id="U9"), **kw)
    assert lookup.call_count == 0
    await SLACK.send_question(Expert(name="Dima", email="Dima@Example.com"), **kw)
    await SLACK.send_question(Expert(name="Dima", email="dima@example.com"), **kw)
    assert lookup.call_count == 1


@respx.mock
async def test_ok_false_raises():
    respx.get(f"{API}/users.lookupByEmail").mock(
        return_value=httpx.Response(200, json={"ok": False, "error": "users_not_found"})
    )
    with pytest.raises(NotifierError, match="users_not_found"):
        await SLACK.send_question(
            Expert(name="Ghost", email="ghost@example.com"),
            meeting_title="t",
            asked_by="a",
            question="q",
            context_lines=[],
        )


@respx.mock
async def test_http_error_and_no_address_raise():
    respx.post(f"{API}/chat.postMessage").mock(return_value=httpx.Response(500))
    with pytest.raises(NotifierError):
        await SLACK.post_reply(SentMessage("slack", "1.1", "D1"), "thanks")
    with pytest.raises(NotifierError):
        await SLACK.resolve_user(Expert(name="Nobody"))


@respx.mock
async def test_post_reply_in_thread():
    post = respx.post(f"{API}/chat.postMessage").mock(return_value=ok(ts="2.2"))
    await SLACK.post_reply(SentMessage("slack", "1.1", "D1"), "Thanks, passed it on")
    assert json.loads(post.calls[0].request.content) == {
        "channel": "D1",
        "thread_ts": "1.1",
        "text": "Thanks, passed it on",
    }


@respx.mock
async def test_bot_user_id_cached():
    route = respx.post(f"{API}/auth.test").mock(return_value=ok(user_id="U_BOT", bot_id="B1"))
    assert await SLACK.bot_user_id() == "U_BOT"
    assert await SLACK.bot_user_id() == "U_BOT"
    assert route.call_count == 1


# ---------- webhook ----------


def sign(body: bytes, ts: int | None = None, secret: str = SECRET) -> dict:
    ts = int(time.time()) if ts is None else ts
    base = f"v0:{ts}:".encode() + body
    sig = "v0=" + hmac.new(secret.encode(), base, hashlib.sha256).hexdigest()
    return {
        "X-Slack-Request-Timestamp": str(ts),
        "X-Slack-Signature": sig,
        "Content-Type": "application/json",
    }


def post(client, payload, headers=None, **sign_kw):
    body = json.dumps(payload).encode()
    h = sign(body, **sign_kw)
    h.update(headers or {})
    r = client.post(URL, content=body, headers=h)
    end = time.monotonic() + 2
    while webhooks_slack._tasks and time.monotonic() < end:
        time.sleep(0.01)
    return r


def callback(event, event_id="Ev1"):
    return {"type": "event_callback", "event_id": event_id, "event": event}


REPLY = {
    "type": "message",
    "channel": "D1",
    "user": "U_DIMA",
    "text": "Upgrade is on the 14th.",
    "ts": "1700000050.000200",
    "thread_ts": "1700000000.000100",
    "channel_type": "im",
}


@pytest.fixture
def hook(monkeypatch):
    calls = []

    async def fake(channel_id, thread_ts, text, user_id):
        calls.append((channel_id, thread_ts, text, user_id))

    monkeypatch.setattr(escalation, "on_expert_reply", fake)
    return calls


@pytest.fixture
def client():
    with respx.mock(assert_all_called=False) as mock:
        mock.post(f"{API}/auth.test").mock(return_value=ok(user_id="U_BOT"))
        yield TestClient(app)


def test_url_verification_echoes(client):
    r = post(client, {"type": "url_verification", "challenge": "abc123", "token": "x"})
    assert r.status_code == 200
    assert r.json() == {"challenge": "abc123"}


def test_thread_reply_calls_hook(client, hook):
    r = post(client, callback(REPLY))
    assert r.status_code == 200
    assert hook == [("D1", "1700000000.000100", "Upgrade is on the 14th.", "U_DIMA")]


def test_bad_signature_401(client, hook):
    r = post(client, callback(REPLY), secret="wrong")
    assert r.status_code == 401
    r = client.post(URL, content=b"{}")
    assert r.status_code == 401
    assert hook == []


def test_stale_signature_401(client, hook):
    r = post(client, callback(REPLY), ts=int(time.time()) - 301)
    assert r.status_code == 401
    assert hook == []


def test_empty_secret_rejects_everything(client, hook, monkeypatch):
    monkeypatch.setenv("SLACK_SIGNING_SECRET", "")
    get_settings.cache_clear()
    r = post(client, {"type": "url_verification", "challenge": "abc"}, secret="")
    assert r.status_code == 401


def test_retry_header_skipped(client, hook):
    r = post(client, callback(REPLY), headers={"X-Slack-Retry-Num": "1"})
    assert r.status_code == 200
    assert hook == []


def test_duplicate_event_id_once(client, hook):
    post(client, callback(REPLY, "EvDup"))
    post(client, callback(REPLY, "EvDup"))
    assert len(hook) == 1


@pytest.mark.parametrize(
    "patch",
    [
        {"bot_id": "B1"},
        {"subtype": "bot_message"},
        {"subtype": "message_changed"},
        {"subtype": "message_deleted"},
        {"user": "U_BOT"},  # our own bot user (auth.test)
        {"thread_ts": None},  # top-level DM
        {"thread_ts": REPLY["ts"]},  # thread parent itself
    ],
)
def test_ignored_messages(client, hook, patch):
    event = {k: v for k, v in {**REPLY, **patch}.items() if v is not None}
    r = post(client, callback(event))
    assert r.status_code == 200
    assert hook == []

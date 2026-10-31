"""M7.1: GET/PUT /settings (secret masking), GET /integrations, POST /integrations/{name}/test."""

import base64
import json

import httpx
import pytest
import respx

from app import runtime, telegram_api
from app.config import get_settings
from app.main import app
from app.notifier.slack import SLACK

DEMO = "demo-t"
AUTH = {"Authorization": f"Bearer {DEMO}"}
TG = "https://api.telegram.org/bot123:tg-token"
JIRA = "https://acme.atlassian.net"


@pytest.fixture(autouse=True)
def env(monkeypatch):
    for k, v in {
        "DEMO_TOKEN": DEMO,
        "DATABASE_URL": "",
        "PUBLIC_BASE_URL": "https://crew.example.com",
        "SLACK_BOT_TOKEN": "xoxb-env-1234",
        "SLACK_SIGNING_SECRET": "",
        "TELEGRAM_BOT_TOKEN": "",
        "TELEGRAM_WEBHOOK_SECRET": "",
        "JIRA_BASE_URL": "",
        "JIRA_EMAIL": "",
        "JIRA_API_TOKEN": "",
        "JIRA_PROJECT_KEY": "",
        "AGENT_NAME": "Atlas",
        "OWNER_NAME": "Artem",
    }.items():
        monkeypatch.setenv(k, v)
    get_settings.cache_clear()
    runtime.reset()
    telegram_api.reset()
    SLACK.reset()
    yield
    runtime.reset()
    telegram_api.reset()
    SLACK.reset()
    get_settings.cache_clear()


def client():
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")


async def test_requires_demo_token():
    async with client() as c:
        rs = [
            await c.get("/settings"),
            await c.put("/settings", json={}, headers={"Authorization": "Bearer nope"}),
            await c.get("/integrations"),
            await c.post("/integrations/slack/test"),
        ]
    assert [r.status_code for r in rs] == [401] * 4
    assert rs[0].json()["error"]["code"] == "unauthorized"


async def test_get_settings_masks_secrets():
    async with client() as c:
        r = await c.get("/settings", headers=AUTH)
    assert r.status_code == 200
    body = r.json()
    assert body["public_base_url"] == "https://crew.example.com"
    assert set(body["values"]) == set(runtime.EDITABLE)
    assert body["values"]["SLACK_BOT_TOKEN"] == {
        "secret": True,
        "value": None,
        "set": True,
        "hint": "…1234",
        "source": "env",
    }
    assert body["values"]["SLACK_SIGNING_SECRET"] == {
        "secret": True,
        "value": None,
        "set": False,
        "hint": None,
        "source": "unset",
    }
    assert body["values"]["AGENT_NAME"] == {
        "secret": False,
        "value": "Atlas",
        "set": True,
        "hint": None,
        "source": "env",
    }
    assert "xoxb-env-1234" not in r.text


async def test_put_settings_partial_and_clear():
    async with client() as c:
        r = await c.put(
            "/settings",
            headers=AUTH,
            json={"OWNER_NAME": "Julian", "SLACK_BOT_TOKEN": "xoxb-ui-9876"},
        )
        assert r.status_code == 200
        v = r.json()["values"]
        assert v["OWNER_NAME"]["value"] == "Julian" and v["OWNER_NAME"]["source"] == "db"
        assert v["SLACK_BOT_TOKEN"]["hint"] == "…9876" and v["SLACK_BOT_TOKEN"]["value"] is None
        assert v["AGENT_NAME"]["source"] == "env"  # untouched
        assert runtime.get("SLACK_BOT_TOKEN") == "xoxb-ui-9876"

        r = await c.put("/settings", headers=AUTH, json={"OWNER_NAME": ""})
        assert r.json()["values"]["OWNER_NAME"] == {
            "secret": False,
            "value": "Artem",
            "set": True,
            "hint": None,
            "source": "env",
        }


async def test_put_settings_unknown_key_is_422():
    async with client() as c:
        r1 = await c.put("/settings", headers=AUTH, json={"OPENAI_API_KEY": "sk-x"})
        r2 = await c.put("/settings", headers=AUTH, json={"AGENT_NAME": 5})
    assert r1.status_code == 422 and r1.json()["error"]["code"] == "validation_error"
    assert r2.status_code == 422 and r2.json()["error"]["code"] == "validation_error"
    assert runtime.source("AGENT_NAME") == "env"


async def test_integrations_overview():
    await runtime.save(
        {
            "SLACK_SIGNING_SECRET": "sig",
            "JIRA_BASE_URL": f"{JIRA}/",
            "JIRA_EMAIL": "a@b.c",
            "JIRA_API_TOKEN": "jt",
            "JIRA_PROJECT_KEY": "PTW",
        }
    )
    async with client() as c:
        r = await c.get("/integrations", headers=AUTH)
    assert r.json() == {
        "slack": {"configured": True, "webhook_url": "https://crew.example.com/webhooks/slack"},
        "telegram": {
            "configured": False,
            "webhook_url": "https://crew.example.com/webhooks/telegram",
            "bot_username": None,
        },
        "jira": {"configured": True, "base_url": JIRA, "project_key": "PTW"},
    }


async def test_unknown_integration_404():
    async with client() as c:
        r = await c.post("/integrations/teams/test", headers=AUTH)
    assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"


@respx.mock
async def test_slack_test_ok_and_error():
    route = respx.post("https://slack.com/api/auth.test").mock(
        side_effect=[
            httpx.Response(
                200, json={"ok": True, "user_id": "UBOT", "user": "crew", "team": "PTW"}
            ),
            httpx.Response(200, json={"ok": False, "error": "invalid_auth"}),
        ]
    )
    async with client() as c:
        ok = (await c.post("/integrations/slack/test", headers=AUTH)).json()
        bad = (await c.post("/integrations/slack/test", headers=AUTH)).json()
    assert ok["ok"] is True and "PTW" in ok["detail"] and "crew" in ok["detail"]
    assert "signing secret" in ok["detail"]
    assert bad == {"ok": False, "detail": "slack auth.test: invalid_auth"}
    assert route.calls[0].request.headers["Authorization"] == "Bearer xoxb-env-1234"


async def test_not_configured_is_ok_false(monkeypatch):
    monkeypatch.setenv("SLACK_BOT_TOKEN", "")
    get_settings.cache_clear()
    async with client() as c:
        s = (await c.post("/integrations/slack/test", headers=AUTH)).json()
        t = (await c.post("/integrations/telegram/test", headers=AUTH)).json()
        j = (await c.post("/integrations/jira/test", headers=AUTH)).json()
    assert s["ok"] is False and t["ok"] is False and j["ok"] is False
    assert t["bot_username"] is None


@respx.mock
async def test_telegram_test_registers_webhook():
    await runtime.save({"TELEGRAM_BOT_TOKEN": "123:tg-token", "TELEGRAM_WEBHOOK_SECRET": "s3cr"})
    me = respx.post(f"{TG}/getMe").mock(
        return_value=httpx.Response(
            200, json={"ok": True, "result": {"id": 1, "is_bot": True, "username": "crew_bot"}}
        )
    )
    hook = respx.post(f"{TG}/setWebhook").mock(
        return_value=httpx.Response(200, json={"ok": True, "result": True})
    )
    async with client() as c:
        r = (await c.post("/integrations/telegram/test", headers=AUTH)).json()
        overview = (await c.get("/integrations", headers=AUTH)).json()
    assert r["ok"] is True and r["bot_username"] == "crew_bot"
    assert me.called
    sent = json.loads(hook.calls.last.request.content)
    assert sent["url"] == "https://crew.example.com/webhooks/telegram"
    assert sent["secret_token"] == "s3cr"
    assert overview["telegram"]["configured"] is True
    assert overview["telegram"]["bot_username"] == "crew_bot"


@respx.mock
@pytest.mark.parametrize("secret", ["", "bad secret!"])
async def test_telegram_test_skips_webhook_without_valid_secret(secret):
    await runtime.save({"TELEGRAM_BOT_TOKEN": "123:tg-token", "TELEGRAM_WEBHOOK_SECRET": secret})
    respx.post(f"{TG}/getMe").mock(
        return_value=httpx.Response(200, json={"ok": True, "result": {"username": "crew_bot"}})
    )
    hook = respx.post(f"{TG}/setWebhook").mock(
        return_value=httpx.Response(200, json={"ok": True, "result": True})
    )
    async with client() as c:
        r = (await c.post("/integrations/telegram/test", headers=AUTH)).json()
    assert r["ok"] is False and "secret" in r["detail"] and r["bot_username"] == "crew_bot"
    assert not hook.called


@respx.mock
async def test_telegram_bad_token_does_not_leak_it():
    await runtime.save({"TELEGRAM_BOT_TOKEN": "123:tg-token"})
    respx.post(f"{TG}/getMe").mock(
        return_value=httpx.Response(
            401, json={"ok": False, "error_code": 401, "description": "Unauthorized"}
        )
    )
    async with client() as c:
        r = (await c.post("/integrations/telegram/test", headers=AUTH)).json()
    assert r == {"ok": False, "detail": "telegram getMe: Unauthorized", "bot_username": None}


@respx.mock
async def test_jira_test_ok_and_unauthorized():
    await runtime.save({"JIRA_BASE_URL": JIRA, "JIRA_EMAIL": "a@b.c", "JIRA_API_TOKEN": "jt"})
    route = respx.get(f"{JIRA}/rest/api/3/myself").mock(
        side_effect=[
            httpx.Response(200, json={"accountId": "x", "displayName": "Artem K"}),
            httpx.Response(401, json={"message": "Unauthorized"}),
        ]
    )
    async with client() as c:
        ok = (await c.post("/integrations/jira/test", headers=AUTH)).json()
        bad = (await c.post("/integrations/jira/test", headers=AUTH)).json()
    assert ok == {"ok": True, "detail": f"Connected to {JIRA} as Artem K"}
    assert bad["ok"] is False and "401" in bad["detail"]
    auth = route.calls[0].request.headers["Authorization"]
    assert auth == "Basic " + base64.b64encode(b"a@b.c:jt").decode()

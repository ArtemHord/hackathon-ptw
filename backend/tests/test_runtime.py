"""M7.1: runtime settings (DB override over env) and the reads that moved to runtime.get."""

import pytest

from app import db, escalation, orchestrator, recall, runtime, webhooks_recall
from app.config import get_settings


@pytest.fixture(autouse=True)
def env(monkeypatch):
    for k, v in {
        "DATABASE_URL": "",
        "AGENT_NAME": "Atlas",
        "OWNER_NAME": "Artem",
        "SLACK_BOT_TOKEN": "xoxb-env",
        "JIRA_AUTO_CREATE": "",
        "TRANSCRIPT_EXTRA_KEYTERMS": "",
    }.items():
        monkeypatch.setenv(k, v)
    monkeypatch.delenv("JIRA_BASE_URL", raising=False)
    get_settings.cache_clear()
    runtime.reset()
    yield
    runtime.reset()
    get_settings.cache_clear()


async def test_env_fallback_and_override():
    assert runtime.get("SLACK_BOT_TOKEN") == "xoxb-env"
    assert runtime.source("SLACK_BOT_TOKEN") == "env"
    assert runtime.source("JIRA_BASE_URL") == "unset"
    await runtime.save({"SLACK_BOT_TOKEN": "  xoxb-db  "})
    assert runtime.get("SLACK_BOT_TOKEN") == "xoxb-db"
    assert runtime.source("SLACK_BOT_TOKEN") == "db"
    await runtime.save({"SLACK_BOT_TOKEN": ""})  # clears the override
    assert runtime.get("SLACK_BOT_TOKEN") == "xoxb-env"
    assert runtime.source("SLACK_BOT_TOKEN") == "env"


async def test_unknown_key_rejected():
    with pytest.raises(KeyError):
        await runtime.save({"OPENAI_API_KEY": "sk-x"})
    assert runtime.get("OPENAI_API_KEY") == get_settings().OPENAI_API_KEY


@pytest.mark.parametrize("v,expected", [("1", True), ("true", True), ("Yes", True), ("", False)])
async def test_get_bool(v, expected):
    await runtime.save({"JIRA_AUTO_CREATE": v})
    assert runtime.get_bool("JIRA_AUTO_CREATE") is expected


async def test_save_and_load_use_db_when_configured(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://fake")
    get_settings.cache_clear()
    store = {"AGENT_NAME": "Nova", "NOT_EDITABLE": "x"}
    calls = []

    async def list_settings():
        return dict(store)

    async def upsert_setting(k, v):
        calls.append(("upsert", k, v))
        store[k] = v

    async def delete_setting(k):
        calls.append(("delete", k))
        store.pop(k, None)

    monkeypatch.setattr(db, "list_settings", list_settings)
    monkeypatch.setattr(db, "upsert_setting", upsert_setting)
    monkeypatch.setattr(db, "delete_setting", delete_setting)

    await runtime.load()
    assert runtime.get("AGENT_NAME") == "Nova"
    assert runtime.get("NOT_EDITABLE") == ""  # ignored: not in EDITABLE
    await runtime.save({"OWNER_NAME": "Julian", "AGENT_NAME": ""})
    assert calls == [("upsert", "OWNER_NAME", "Julian"), ("delete", "AGENT_NAME")]
    assert runtime.get("OWNER_NAME") == "Julian" and runtime.get("AGENT_NAME") == "Atlas"


async def test_load_never_raises(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://fake")
    get_settings.cache_clear()

    async def boom():
        raise RuntimeError("relation app_settings does not exist")

    monkeypatch.setattr(db, "list_settings", boom)
    await runtime.load()
    assert runtime.get("AGENT_NAME") == "Atlas"


async def test_names_follow_runtime():
    assert recall.bot_name() == "Atlas (AI) for Artem"
    await runtime.save({"AGENT_NAME": "Nova", "OWNER_NAME": "Julian"})
    assert recall.bot_name() == "Nova (AI) for Julian"
    assert recall.keyterms() == ["Nova", "Hey Nova", "Okay Nova"]
    body = recall.build_bot_body("https://meet.google.com/x", "m_01", "deepgram")
    assert body["bot_name"] == "Nova (AI) for Julian"
    deepgram = body["recording_config"]["transcript"]["provider"]["deepgram_streaming"]
    assert deepgram["keyterm"][:3] == ["Nova", "Hey Nova", "Okay Nova"]
    assert webhooks_recall.is_bot_speaker("Nova (AI) for Julian")
    assert webhooks_recall.is_bot_speaker("Call Crew (AI) for Artem")
    assert not webhooks_recall.is_bot_speaker("Atlas (AI) for Artem")
    assert orchestrator.parse_trigger("Nova, what is our API limit?") == "what is our API limit?"
    system = orchestrator.build_messages("", [], "Misha", "q?", "- Dima: infra")[0]["content"]
    assert system.startswith("You are Nova, Julian's delegate in this call.")
    assert '"what did Julian finish"' in system and "- Dima: infra" in system


async def test_slack_token_override_selects_real_notifier(monkeypatch):
    monkeypatch.setenv("SLACK_BOT_TOKEN", "")
    get_settings.cache_clear()
    from app.notifier.fake import FAKE
    from app.notifier.slack import SLACK

    assert escalation._notifier_for("slack") is FAKE
    await runtime.save({"SLACK_BOT_TOKEN": "xoxb-ui"})
    assert escalation._notifier_for("slack") is SLACK

"""M10.2: "Atlas, ask <teammate> ..." finds the person in the Slack workspace, DMs them with an
@mention, and a plain DM reply (not in the thread) answers the open question. respx, no network."""

import httpx
import pytest
import respx

from app import escalation, runtime
from app.config import get_settings
from app.notifier import slack as slack_mod
from app.notifier.slack import SLACK, name_score
from app.webhooks_slack import parse_dm

API = "https://slack.com/api"
MEMBERS = [
    {"id": "U_ART", "name": "hordiienko.artem1", "profile": {"real_name": "Artem Hordiienko"}},
    {
        "id": "U_JAC",
        "name": "tobytefor",
        "profile": {"real_name": "Jacob", "display_name": "Jacob"},
    },
    {"id": "U_MIK", "name": "mikhailtroian", "profile": {"real_name": "mikhailtroian"}},
    {"id": "U_JUL", "name": "s31873", "profile": {"real_name": "Julian Pulawski"}},
    {"id": "U_BOT", "name": "atlas", "is_bot": True, "profile": {"real_name": "Atlas"}},
]


@pytest.fixture(autouse=True)
def env(monkeypatch):
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
    monkeypatch.setenv("DATABASE_URL", "")
    get_settings.cache_clear()
    runtime.reset()
    SLACK.reset()
    monkeypatch.setattr(escalation, "_cache", None)
    yield
    SLACK.reset()
    get_settings.cache_clear()


def members_route():
    return respx.get(f"{API}/users.list").mock(
        return_value=httpx.Response(200, json={"ok": True, "members": MEMBERS})
    )


@pytest.mark.parametrize(
    "spoken,uid",
    [
        ("Artem", "U_ART"),
        ("Artem Hordiienko", "U_ART"),
        ("Jacob", "U_JAC"),
        ("Mikhail", "U_MIK"),
        ("mikhailtoian", "U_MIK"),  # typo / ASR
        ("Juliana Pulawski", "U_JUL"),  # ASR
        ("Julian", "U_JUL"),
    ],
)
@respx.mock
async def test_find_user_by_spoken_name(spoken, uid):
    members_route()
    user = await SLACK.find_user(spoken)
    assert user is not None and user["id"] == uid


@respx.mock
async def test_find_user_none_for_unknown_and_skips_bots():
    members_route()
    assert await SLACK.find_user("Dima") is None
    assert await SLACK.find_user("Atlas") is None  # the bot itself


def test_name_score_exact_and_prefix():
    assert name_score("jacob", "Jacob") == 1.0
    assert name_score("artem", "Artem Hordiienko") >= 0.9
    assert name_score("infra", "Artem Hordiienko") < slack_mod.NAME_MATCH_MIN


@pytest.mark.parametrize(
    "topic,question,first",
    [
        ("Artem", "ask Artem whether the token rotation is done", "Artem"),
        ("", "ping Jacob about the deploy", "Jacob"),
        ("Mikhail", "check with Mikhail if billing is final", "Mikhail"),
    ],
)
def test_requested_names(topic, question, first):
    assert escalation.requested_names(topic, question)[0] == first


def test_requested_names_needs_an_explicit_ask():
    assert escalation.requested_names("infra", "when do we migrate to Postgres 17?") == []
    assert escalation.requested_names("", "ask the team about it") == []


@respx.mock
async def test_slack_person_offline_expert_with_user_id():
    members_route()
    e = await escalation.slack_person("Artem", "ask Artem whether the export is on track")
    assert e is not None and e.slack_user_id == "U_ART" and e.name == "Artem Hordiienko"


@respx.mock
async def test_slack_person_not_without_token(monkeypatch):
    monkeypatch.setenv("SLACK_BOT_TOKEN", "")
    get_settings.cache_clear()
    route = members_route()
    assert await escalation.slack_person("Artem", "ask Artem about it") is None
    assert not route.called


@respx.mock
async def test_question_dm_tags_the_person():
    respx.post(f"{API}/conversations.open").mock(
        return_value=httpx.Response(200, json={"ok": True, "channel": {"id": "D_ART"}})
    )
    post = respx.post(f"{API}/chat.postMessage").mock(
        return_value=httpx.Response(200, json={"ok": True, "ts": "1.1", "channel": "D_ART"})
    )
    expert = escalation.Expert(name="Artem Hordiienko", slack_user_id="U_ART")
    await SLACK.send_question(
        expert, meeting_title="INC-024", asked_by="Kamil", question="Q?", context_lines=[]
    )
    import json

    assert json.loads(post.calls[0].request.content)["text"].startswith("<@U_ART> ")


def test_parse_dm_top_level_only():
    base = {"type": "message", "channel_type": "im", "channel": "D1", "user": "U1", "ts": "2.0"}
    assert parse_dm({**base, "text": "Thursday"}) == ("D1", "Thursday", "U1")
    assert parse_dm({**base, "text": "x", "thread_ts": "1.0"}) is None  # thread reply
    assert parse_dm({**base, "text": "x", "bot_id": "B1"}) is None
    assert parse_dm({**base, "channel_type": "channel", "text": "x"}) is None


async def test_plain_dm_answers_open_question(monkeypatch):
    seen = {}

    async def open_by_channel(channel):
        return {"id": "e1", "external_msg_id": "1.1", "status": "waiting"}

    async def on_reply(channel, thread_ts, text, user):
        seen.update(channel=channel, thread_ts=thread_ts, text=text, user=user)

    monkeypatch.setattr(escalation.db, "get_open_escalation_by_channel", open_by_channel)
    monkeypatch.setattr(escalation, "_on_reply", on_reply)
    await escalation.on_expert_dm("D_ART", " Yes, done on Friday ", "U_ART")
    assert seen == {
        "channel": "D_ART",
        "thread_ts": "1.1",
        "text": "Yes, done on Friday",
        "user": "U_ART",
    }

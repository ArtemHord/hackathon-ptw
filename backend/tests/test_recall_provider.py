"""M6.6: TRANSCRIPT_PROVIDER=deepgram (nova-3 + keyterm), one recallai fallback on 400."""

import json
import logging

import httpx
import respx

from app.config import get_settings
from tests.test_meetings import AUTH, BODY, RECALL, client, env, store  # noqa: F401

RECALLAI = {"recallai_streaming": {"mode": "prioritize_low_latency", "language_code": "en"}}
DEEPGRAM = {
    "deepgram_streaming": {
        "model": "nova-3",
        "language": "en",
        "keyterm": ["Atlas", "Hey Atlas", "Okay Atlas"],
        "endpointing": 500,
    }
}


def _deepgram(monkeypatch, extra: str = ""):
    monkeypatch.setenv("TRANSCRIPT_PROVIDER", "deepgram")
    monkeypatch.setenv("TRANSCRIPT_EXTRA_KEYTERMS", extra)
    get_settings.cache_clear()


def _sent(call) -> dict:
    return json.loads(call.request.content)


def _assert_rest_unchanged(sent: dict):
    rc = sent["recording_config"]
    assert set(rc) == {"transcript", "realtime_endpoints"}
    (ep,) = rc["realtime_endpoints"]
    assert ep["type"] == "webhook"
    assert ep["events"] == ["transcript.data"]
    assert ep["url"].startswith("https://crew.example.com/webhooks/recall/transcript?")
    assert sent["output_media"]["camera"]["kind"] == "webpage"
    assert sent["automatic_leave"] == {"waiting_room_timeout": 600}


@respx.mock
def test_default_provider_is_recallai_low_latency(client, store):  # noqa: F811
    route = respx.post(f"{RECALL}/api/v1/bot/").mock(
        return_value=httpx.Response(201, json={"id": "bot_1"})
    )
    assert client.post("/meetings", json=BODY, headers=AUTH).status_code == 201
    assert route.call_count == 1
    sent = _sent(route.calls.last)
    assert sent["recording_config"]["transcript"] == {"provider": RECALLAI}
    _assert_rest_unchanged(sent)


@respx.mock
def test_deepgram_body_shape(client, store, monkeypatch):  # noqa: F811
    _deepgram(monkeypatch)
    route = respx.post(f"{RECALL}/api/v1/bot/").mock(
        return_value=httpx.Response(201, json={"id": "bot_2"})
    )
    r = client.post("/meetings", json=BODY, headers=AUTH)
    assert r.status_code == 201, r.text
    assert route.call_count == 1
    sent = _sent(route.calls.last)
    assert sent["recording_config"]["transcript"] == {"provider": DEEPGRAM}
    assert (
        sent["recording_config"]["transcript"]["provider"]["deepgram_streaming"]["endpointing"]
        == 500
    )  # keeps "Okay Atlas," and the question in one utterance
    _assert_rest_unchanged(sent)
    assert store["meetings"][r.json()["id"]]["recall_bot_id"] == "bot_2"


def test_extra_keyterms_from_config(monkeypatch):
    _deepgram(monkeypatch, extra=" Atlas AI , ,Hi Atlas")
    assert get_settings().transcript_keyterms == [
        "Atlas",
        "Hey Atlas",
        "Okay Atlas",
        "Atlas AI",
        "Hi Atlas",
    ]


@respx.mock
def test_deepgram_400_retries_once_with_recallai(client, store, monkeypatch, caplog):  # noqa: F811
    _deepgram(monkeypatch)
    route = respx.post(f"{RECALL}/api/v1/bot/").mock(
        side_effect=[
            httpx.Response(400, json={"recording_config": ["Deepgram credentials missing"]}),
            httpx.Response(201, json={"id": "bot_3"}),
        ]
    )
    with caplog.at_level(logging.WARNING, logger="app.recall"):
        r = client.post("/meetings", json=BODY, headers=AUTH)
    assert r.status_code == 201, r.text
    assert r.json()["status"] == "joining"
    assert route.call_count == 2
    first, second = (_sent(c) for c in route.calls)
    assert first["recording_config"]["transcript"] == {"provider": DEEPGRAM}
    assert second["recording_config"]["transcript"] == {"provider": RECALLAI}
    _assert_rest_unchanged(second)
    assert store["meetings"][r.json()["id"]]["recall_bot_id"] == "bot_3"
    assert any("Deepgram credentials missing" in rec.getMessage() for rec in caplog.records)


@respx.mock
def test_deepgram_400_then_fallback_fails_is_502(client, store, monkeypatch):  # noqa: F811
    _deepgram(monkeypatch)
    route = respx.post(f"{RECALL}/api/v1/bot/").mock(return_value=httpx.Response(400, json={}))
    r = client.post("/meetings", json=BODY, headers=AUTH)
    assert r.status_code == 502
    assert route.call_count == 2  # exactly one retry
    (m,) = store["meetings"].values()
    assert m["status"] == "failed"


@respx.mock
def test_deepgram_non_400_error_is_502_without_retry(client, store, monkeypatch):  # noqa: F811
    _deepgram(monkeypatch)
    route = respx.post(f"{RECALL}/api/v1/bot/").mock(return_value=httpx.Response(500))
    r = client.post("/meetings", json=BODY, headers=AUTH)
    assert r.status_code == 502
    assert r.json()["error"]["code"] == "upstream_error"
    assert route.call_count == 1
    (m,) = store["meetings"].values()
    assert m["status"] == "failed"

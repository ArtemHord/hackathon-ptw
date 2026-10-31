import json

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from app import agent_voice, speech, tts
from app.config import get_settings
from app.main import app

URL = "https://api.elevenlabs.io/v1/text-to-speech/voice-1"
AUTH = {"Authorization": "Bearer demo-t"}


@pytest.fixture(autouse=True)
def env(monkeypatch):
    for k, v in {
        "WEBHOOK_TOKEN": "wh-t",
        "DEMO_TOKEN": "demo-t",
        "DATABASE_URL": "",
        "ELEVENLABS_API_KEY": "xi-key",
        "ELEVENLABS_VOICE_ID": "voice-1",
        "ELEVENLABS_MODEL_ID": "model-x",
    }.items():
        monkeypatch.setenv(k, v)
    get_settings.cache_clear()
    tts.reset_filler()
    yield
    get_settings.cache_clear()
    tts.reset_filler()


@respx.mock
def test_tts_ok_and_request_shape():
    route = respx.post(URL).mock(return_value=httpx.Response(200, content=b"MP3DATA"))
    r = TestClient(app).post("/tts", json={"text": "The limit is 50 rps."}, headers=AUTH)
    assert r.status_code == 200
    assert r.headers["content-type"] == "audio/mpeg"
    assert r.content == b"MP3DATA"
    req = route.calls[0].request
    assert req.url.params["output_format"] == "mp3_44100_128"
    assert req.headers["xi-api-key"] == "xi-key"
    assert json.loads(req.content) == {"text": "The limit is 50 rps.", "model_id": "model-x"}


@respx.mock
def test_tts_requires_bearer():
    route = respx.post(URL).mock(return_value=httpx.Response(200, content=b"x"))
    assert TestClient(app).post("/tts", json={"text": "hi"}).status_code == 401
    assert not route.called


@respx.mock
def test_tts_upstream_500_is_502():
    respx.post(URL).mock(return_value=httpx.Response(500))
    r = TestClient(app).post("/tts", json={"text": "hi"}, headers=AUTH)
    assert r.status_code == 502
    assert r.json()["error"]["code"] == "upstream_error"


@respx.mock
def test_tts_validation():
    respx.post(URL).mock(return_value=httpx.Response(200, content=b"x"))
    c = TestClient(app)
    assert c.post("/tts", json={"text": "  "}, headers=AUTH).status_code == 422
    assert c.post("/tts", json={"text": "a" * 1001}, headers=AUTH).status_code == 422


@respx.mock
async def test_filler_cached():
    route = respx.post(URL).mock(return_value=httpx.Response(200, content=b"FILL"))
    assert await tts.filler() == b"FILL"
    assert await tts.filler() == b"FILL"
    assert route.call_count == 1


@respx.mock
async def test_say_and_say_filler_call_play(monkeypatch):
    respx.post(URL).mock(return_value=httpx.Response(200, content=b"MP3"))
    calls = []

    async def fake_play(meeting_id, mp3, text=None):
        calls.append((meeting_id, mp3, text))
        return True

    monkeypatch.setattr(agent_voice, "play", fake_play)
    assert await speech.say("m_1", "Hello there") is True
    assert await speech.say_filler("m_1") is True
    assert calls == [("m_1", b"MP3", "Hello there"), ("m_1", b"MP3", tts.FILLER_TEXT)]


@respx.mock
async def test_say_false_on_upstream_error():
    respx.post(URL).mock(return_value=httpx.Response(500))
    assert await speech.say("m_1", "Hello") is False


@respx.mock
def test_debug_say(monkeypatch):
    respx.post(URL).mock(return_value=httpx.Response(200, content=b"MP3"))

    async def fake_play(meeting_id, mp3, text=None):
        return True

    monkeypatch.setattr(agent_voice, "play", fake_play)
    c = TestClient(app)
    assert c.post("/debug/say?meeting_id=m_1&token=bad", json={"text": "hi"}).status_code == 401
    r = c.post("/debug/say?meeting_id=m_1&token=wh-t", json={"text": "hi"})
    assert r.json() == {"ok": True, "delivered": True}


def test_boots_without_key(monkeypatch):
    monkeypatch.setenv("ELEVENLABS_API_KEY", "")
    get_settings.cache_clear()
    with TestClient(app) as c:
        assert c.get("/health").json() == {"status": "ok"}

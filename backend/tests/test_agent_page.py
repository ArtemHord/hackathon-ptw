import base64
import time

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app import agent_voice
from app.config import get_settings
from app.main import app


@pytest.fixture(autouse=True)
def env(monkeypatch):
    for k, v in {"WEBHOOK_TOKEN": "wh-t", "DEMO_TOKEN": "demo-t", "DATABASE_URL": ""}.items():
        monkeypatch.setenv(k, v)
    get_settings.cache_clear()
    agent_voice._pages.clear()
    agent_voice._speaking.clear()
    yield
    get_settings.cache_clear()


def wait_for(cond, timeout=2.0):
    end = time.monotonic() + timeout
    while not cond() and time.monotonic() < end:
        time.sleep(0.01)
    return cond()


def test_agent_page_served():
    r = TestClient(app).get("/agent?meeting_id=m_01&token=x")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    assert "Call Crew" in r.text
    assert "/agent-page/ws" in r.text


def test_ws_round_trip():
    client = TestClient(app)
    with client.websocket_connect("/agent-page/ws?meeting_id=m_01&token=wh-t") as ws:
        assert wait_for(lambda: agent_voice.connected("m_01") == 1)
        assert ws.portal.call(agent_voice.play, "m_01", b"ID3fake-mp3") is True
        msg = ws.receive_json()
        assert msg["type"] == "play" and msg["id"]
        assert base64.b64decode(msg["audio_b64"]) == b"ID3fake-mp3"

        assert agent_voice.is_speaking("m_01") is False
        ws.send_json({"type": "speaking", "value": True, "id": msg["id"]})
        assert wait_for(lambda: agent_voice.is_speaking("m_01"))
        ws.send_json({"type": "speaking", "value": False, "id": msg["id"]})
        assert wait_for(lambda: not agent_voice.is_speaking("m_01"))

        # other meetings are unaffected
        assert ws.portal.call(agent_voice.play, "m_02", b"x") is False
    assert wait_for(lambda: agent_voice.connected("m_01") == 0)
    assert agent_voice.is_speaking("m_01") is False


def test_bad_token_closes_4401():
    client = TestClient(app)
    for url in ("/agent-page/ws?meeting_id=m_01&token=nope", "/agent-page/ws?meeting_id=m_01"):
        with client.websocket_connect(url) as ws:
            with pytest.raises(WebSocketDisconnect) as e:
                ws.receive_json()
            assert e.value.code == 4401
    assert agent_voice.connected("m_01") == 0


async def test_play_without_page_returns_false():
    assert await agent_voice.play("m_none", b"mp3") is False
    assert await agent_voice.play_test_tone("m_none") is False


def test_debug_say_tone():
    client = TestClient(app)
    assert client.post("/debug/say-tone?meeting_id=m_01&token=bad").status_code == 401
    r = client.post("/debug/say-tone?meeting_id=m_01&token=wh-t")
    assert r.status_code == 200 and r.json()["delivered"] is False
    with client.websocket_connect("/agent-page/ws?meeting_id=m_01&token=wh-t") as ws:
        assert wait_for(lambda: agent_voice.connected("m_01") == 1)
        r = client.post("/debug/say-tone?meeting_id=m_01&token=wh-t")
        assert r.json()["delivered"] is True
        assert ws.receive_json()["type"] == "tone"


def test_reconnect_clears_stuck_flag():
    client = TestClient(app)
    with client.websocket_connect("/agent-page/ws?meeting_id=m_01&token=wh-t") as old:
        old.send_json({"type": "speaking", "value": True, "id": "a"})
        assert wait_for(lambda: agent_voice.is_speaking("m_01"))
        # page reconnects while the old socket is still half-open
        with client.websocket_connect("/agent-page/ws?meeting_id=m_01&token=wh-t"):
            assert wait_for(lambda: agent_voice.connected("m_01") == 2)
            assert agent_voice.is_speaking("m_01") is False
        assert wait_for(lambda: agent_voice.connected("m_01") == 1)
        old.send_json({"type": "speaking", "value": True, "id": "b"})
        assert wait_for(lambda: agent_voice.is_speaking("m_01"))


def test_speaking_flag_expires(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(agent_voice.time, "monotonic", lambda: now[0])
    agent_voice._set_speaking("m_01", True)
    assert agent_voice.is_speaking("m_01") is True
    now[0] += agent_voice.SPEAKING_TTL_S - 1
    assert agent_voice.is_speaking("m_01") is True
    now[0] += 2
    assert agent_voice.is_speaking("m_01") is False


@pytest.mark.parametrize(
    "path,ctype",
    [
        ("/agent/orb.js", "text/javascript"),
        ("/agent/assets/DrukWideCyr.ttf", "font/ttf"),
        ("/agent/assets/Onest-latin.woff2", "font/woff2"),
        ("/agent/assets/JetBrainsMono-latin.woff2", "font/woff2"),
    ],
)
def test_agent_assets_served(path, ctype):
    r = TestClient(app).get(path)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith(ctype)
    assert len(r.content) > 1000


def test_agent_assets_whitelist():
    client = TestClient(app)
    assert client.get("/agent/assets/index.html").status_code == 404
    assert client.get("/agent/assets/..%2Findex.html").status_code == 404
    page = client.get("/agent").text
    assert "/agent/orb.js" in page and "/agent/assets/DrukWideCyr.ttf" in page


def test_orb_messages_delivered():
    client = TestClient(app)
    with client.websocket_connect("/agent-page/ws?meeting_id=m_01&token=wh-t") as ws:
        assert wait_for(lambda: agent_voice.connected("m_01") == 1)
        call = ws.portal.call

        assert call(agent_voice.send_state, "m_01", "thinking") is True
        assert ws.receive_json() == {"type": "state", "state": "thinking"}

        assert call(agent_voice.send_ask, "m_01", "esc_1", "What is p95?", "Bob", 120) is True
        assert ws.receive_json() == {
            "type": "ask",
            "id": "esc_1",
            "question": "What is p95?",
            "expert": "Bob",
            "timeout_s": 120,
        }

        assert call(agent_voice.send_ask_done, "m_01", "esc_1", "answered") is True
        assert ws.receive_json() == {"type": "ask_done", "id": "esc_1", "result": "answered"}

        # invalid values are refused, not sent
        assert call(agent_voice.send_state, "m_01", "dancing") is False
        assert call(agent_voice.send_ask_done, "m_01", "esc_1", "maybe") is False
        assert call(agent_voice.send_ask_done, "m_01", "esc_1", "timeout") is True
        assert ws.receive_json()["result"] == "timeout"


async def test_orb_sends_without_page_or_on_error(monkeypatch):
    assert await agent_voice.send_state("m_none", "idle") is False
    assert await agent_voice.send_ask("m_none", "e", "q", "Bob", 120) is False
    assert await agent_voice.send_ask_done("m_none", "e", "timeout") is False

    async def boom(*a, **k):
        raise RuntimeError("socket on fire")

    monkeypatch.setattr(agent_voice, "_send", boom)
    assert await agent_voice.send_state("m_01", "thinking") is False
    assert await agent_voice.send_ask("m_01", "e", "q", "Bob", "x") is False
    assert await agent_voice.send_ask_done("m_01", "e", "answered") is False

import time

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app import db, webhooks_recall
from app.config import get_settings
from app.main import app

URL = "/webhooks/recall/transcript?meeting_id=m_01&token=wh-t"


@pytest.fixture(autouse=True)
def env(monkeypatch):
    for k, v in {"WEBHOOK_TOKEN": "wh-t", "DEMO_TOKEN": "demo-t", "DATABASE_URL": ""}.items():
        monkeypatch.setenv(k, v)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def store(monkeypatch):
    """In-memory utterances with the same unique key as the DB."""
    rows: dict[tuple, dict] = {}
    hooks: list[tuple[str, dict]] = []

    async def insert_utterance(meeting_id, speaker, text, ts_start, ts_end=None):
        key = (meeting_id, speaker, ts_start)
        if key in rows:
            return None
        rows[key] = {
            "id": f"u_{len(rows) + 1:02d}",
            "meeting_id": meeting_id,
            "speaker": speaker,
            "text": text,
            "ts_start": ts_start,
            "ts_end": ts_end,
        }
        return dict(rows[key])

    async def hook(meeting_id, utterance):
        hooks.append((meeting_id, utterance))

    monkeypatch.setattr(db, "insert_utterance", insert_utterance)
    monkeypatch.setattr(webhooks_recall, "orchestrator_hook", hook)
    return {"rows": rows, "hooks": hooks}


def payload(name="Julian", start=305.2, words=("Atlas,", "what", "is", "our", "API", "limit?")):
    return {
        "event": "transcript.data",
        "data": {
            "data": {
                "words": [
                    {
                        "text": w,
                        "start_timestamp": {"relative": start + i * 0.3},
                        "end_timestamp": {"relative": start + i * 0.3 + 0.25},
                    }
                    for i, w in enumerate(words)
                ],
                "language_code": "en",
                "participant": {"id": 100, "name": name, "is_host": False, "platform": None},
            },
            "realtime_endpoint": {"id": "re_1", "metadata": {}},
            "transcript": {"id": "tr_1", "metadata": {}},
            "recording": {"id": "rec_1", "metadata": {}},
            "bot": {"id": "bot_1", "metadata": {}},
        },
    }


def drain(timeout=2.0):
    end = time.monotonic() + timeout
    while webhooks_recall._tasks and time.monotonic() < end:
        time.sleep(0.01)
    assert not webhooks_recall._tasks


def test_parse_transcript():
    p = webhooks_recall.parse_transcript(payload())
    assert p["speaker"] == "Julian"
    assert p["text"] == "Atlas, what is our API limit?"
    assert p["ts_start"] == pytest.approx(305.2)
    assert p["ts_end"] == pytest.approx(305.2 + 5 * 0.3 + 0.25)


@pytest.mark.parametrize("name", ["Atlas (AI) for Artem", "Call Crew (AI) for Artem"])
def test_is_bot_speaker(name):
    assert webhooks_recall.is_bot_speaker(name)
    assert webhooks_recall.parse_transcript(payload(name=name)) is None


def test_parse_skips_bot_and_empty():
    assert not webhooks_recall.is_bot_speaker("Julian")
    assert webhooks_recall.parse_transcript(payload(name="Atlas (AI) for Artem")) is None
    assert webhooks_recall.parse_transcript(payload(words=())) is None
    assert webhooks_recall.parse_transcript({"event": "bot.status_change"}) is None


def test_parse_no_name_falls_back_to_id():
    p = payload(name=None)
    assert webhooks_recall.parse_transcript(p)["speaker"] == "Participant 100"


def test_bad_token_401(store):
    with TestClient(app) as c:
        r = c.post("/webhooks/recall/transcript?meeting_id=m_01&token=nope", json=payload())
        assert r.status_code == 401
        assert r.json()["error"]["code"] == "unauthorized"
        r = c.post("/webhooks/recall/transcript?meeting_id=m_01", json=payload())
        assert r.status_code == 401
    assert store["rows"] == {}


def test_ws_bad_token_closes_4401():
    with TestClient(app) as c:
        with pytest.raises(WebSocketDisconnect) as e:
            with c.websocket_connect("/app/ws?meeting_id=m_01&token=bad") as ws:
                ws.receive_json()
        assert e.value.code == 4401


def test_duplicate_is_one_insert_one_event(store):
    with TestClient(app) as c:
        with c.websocket_connect("/app/ws?meeting_id=m_01&token=demo-t") as ws:
            assert c.post(URL, json=payload()).status_code == 200
            assert c.post(URL, json=payload()).status_code == 200  # Recall retry
            drain()
            # a different line next: if the retry had published, it would arrive first
            r = c.post(URL, json=payload(start=310.0, words=("Sounds", "good.")))
            assert r.status_code == 200
            first = ws.receive_json()
            second = ws.receive_json()

    assert len(store["rows"]) == 2
    assert first["type"] == "utterance" and first["meeting_id"] == "m_01"
    assert first["ts"].endswith("Z") and "T" in first["ts"]
    assert first["data"] == {
        "id": "u_01",
        "speaker": "Julian",
        "text": "Atlas, what is our API limit?",
        "ts": 305,
    }
    assert set(first["data"]) == {"id", "speaker", "text", "ts"}  # mocks/ws_utterance.json
    assert second["data"]["text"] == "Sounds good." and second["data"]["ts"] == 310
    assert [h[1]["id"] for h in store["hooks"]] == ["u_01", "u_02"]


def test_bot_speech_skipped(store):
    with TestClient(app) as c:
        with c.websocket_connect("/app/ws?meeting_id=m_01&token=demo-t") as ws:
            c.post(URL, json=payload(name="Call Crew (AI) for Artem"))
            c.post(URL, json=payload(name="Atlas (AI) for Artem", start=0.5))
            drain()
            c.post(URL, json=payload(start=1.0, words=("Hi.",)))
            msg = ws.receive_json()
    assert msg["data"]["text"] == "Hi."
    assert len(store["rows"]) == 1 and len(store["hooks"]) == 1


def test_other_meeting_does_not_receive(store):
    with TestClient(app) as c:
        with c.websocket_connect("/app/ws?meeting_id=m_02&token=demo-t") as other:
            with c.websocket_connect("/app/ws?meeting_id=m_01&token=demo-t") as ws:
                c.post(URL, json=payload())
                assert ws.receive_json()["data"]["id"] == "u_01"
                drain()
                c.post(
                    "/webhooks/recall/transcript?meeting_id=m_02&token=wh-t",
                    json=payload(start=2.0, words=("Other.",)),
                )
                assert other.receive_json()["data"]["text"] == "Other."

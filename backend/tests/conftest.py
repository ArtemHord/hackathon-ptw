import pytest

from app.config import get_settings


@pytest.fixture(autouse=True)
def _agent_tools_off(monkeypatch):
    """M8.1: tool calling defaults to on in the app; tests opt in (test_agent_tools.py), so
    tests written for the chat_json path never send an unmocked /v1/responses request."""
    monkeypatch.setenv("AGENT_TOOLS", "false")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()

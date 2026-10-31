"""The ONE OpenAI client: Chat Completions with Structured Outputs (strict JSON schema).

POST {BASE}/v1/chat/completions, body {"model", "messages", "response_format":
{"type": "json_schema", "json_schema": {"name", "strict": true, "schema"}}}.
Plain httpx instead of the `openai` SDK: SDK 3.x runs on httpx2, which respx cannot
intercept, so tests would hit the real network. Model comes from OPENAI_CHAT_MODEL.
"""

import json
import logging
from typing import Any

import httpx

from app.config import get_settings

log = logging.getLogger(__name__)

BASE_URL = "https://api.openai.com/v1"
TIMEOUT_S = 15.0

_client: httpx.AsyncClient | None = None


class LLMError(Exception):
    """OpenAI unavailable, misconfigured, refused or returned junk."""


def _http() -> httpx.AsyncClient:
    # One pooled client: keeps the TLS connection warm between "Atlas, ..." triggers.
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(base_url=BASE_URL, timeout=TIMEOUT_S)
    return _client


async def close() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


async def chat_json(
    messages: list[dict[str, str]], schema_name: str, schema: dict[str, Any]
) -> dict[str, Any]:
    """Return the model's JSON object, guaranteed (by the API) to match `schema`."""
    s = get_settings()
    if not (s.OPENAI_API_KEY and s.OPENAI_CHAT_MODEL):
        raise LLMError("OpenAI is not configured (OPENAI_API_KEY / OPENAI_CHAT_MODEL)")
    body = {
        "model": s.OPENAI_CHAT_MODEL,
        "messages": messages,
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": schema_name, "strict": True, "schema": schema},
        },
    }
    try:
        r = await _http().post(
            "/chat/completions",
            headers={"Authorization": f"Bearer {s.OPENAI_API_KEY}"},
            json=body,
        )
    except httpx.HTTPError as e:
        raise LLMError(f"OpenAI request failed: {e.__class__.__name__}") from e
    if r.status_code != 200:
        raise LLMError(f"OpenAI returned {r.status_code}: {r.text[:200]}")
    try:
        message = r.json()["choices"][0]["message"]
    except (ValueError, KeyError, IndexError, TypeError) as e:
        raise LLMError("OpenAI response has no message") from e
    if message.get("refusal"):
        raise LLMError(f"OpenAI refused: {message['refusal'][:200]}")
    try:
        data = json.loads(message.get("content") or "")
    except ValueError as e:
        raise LLMError("OpenAI content is not JSON") from e
    if not isinstance(data, dict):
        raise LLMError("OpenAI content is not a JSON object")
    return data


EMBED_BATCH = 96


async def embed(texts: list[str]) -> list[list[float]]:
    """Embeddings (OPENAI_EMBED_MODEL), batched; same order as `texts`."""
    s = get_settings()
    if not (s.OPENAI_API_KEY and s.OPENAI_EMBED_MODEL):
        raise LLMError("OpenAI is not configured (OPENAI_API_KEY / OPENAI_EMBED_MODEL)")
    out: list[list[float]] = []
    for i in range(0, len(texts), EMBED_BATCH):
        batch = texts[i : i + EMBED_BATCH]
        try:
            r = await _http().post(
                "/embeddings",
                headers={"Authorization": f"Bearer {s.OPENAI_API_KEY}"},
                json={"model": s.OPENAI_EMBED_MODEL, "input": batch},
            )
        except httpx.HTTPError as e:
            raise LLMError(f"OpenAI request failed: {e.__class__.__name__}") from e
        if r.status_code != 200:
            raise LLMError(f"OpenAI returned {r.status_code}: {r.text[:200]}")
        try:
            data = sorted(r.json()["data"], key=lambda d: d["index"])
            vecs = [[float(x) for x in d["embedding"]] for d in data]
        except (ValueError, KeyError, TypeError) as e:
            raise LLMError("OpenAI embeddings response malformed") from e
        if len(vecs) != len(batch):
            raise LLMError("OpenAI embeddings count mismatch")
        out.extend(vecs)
    return out

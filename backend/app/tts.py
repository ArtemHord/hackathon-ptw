"""ElevenLabs text-to-speech (REST). The only module that talks to ElevenLabs.

POST {BASE}/v1/text-to-speech/{voice_id}?output_format=mp3_44100_128
headers: xi-api-key, body: {"text", "model_id"}. Model and voice come from env.
A fast model (e.g. eleven_flash_v2_5) is the latency lever.
"""

import asyncio
import logging

import httpx

from app.config import get_settings

log = logging.getLogger(__name__)

BASE_URL = "https://api.elevenlabs.io"
OUTPUT_FORMAT = "mp3_44100_128"
TIMEOUT_S = 10.0
FILLER_TEXT = "One sec, let me check."

_filler: bytes | None = None
_filler_lock = asyncio.Lock()


class TTSError(Exception):
    """ElevenLabs unavailable, misconfigured or returned an error."""


async def synthesize(text: str) -> bytes:
    s = get_settings()
    if not (s.ELEVENLABS_API_KEY and s.ELEVENLABS_VOICE_ID):
        raise TTSError("ElevenLabs is not configured")
    body: dict[str, str] = {"text": text}
    if s.ELEVENLABS_MODEL_ID:
        body["model_id"] = s.ELEVENLABS_MODEL_ID
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_S) as client:
            r = await client.post(
                f"{BASE_URL}/v1/text-to-speech/{s.ELEVENLABS_VOICE_ID}",
                params={"output_format": OUTPUT_FORMAT},
                headers={"xi-api-key": s.ELEVENLABS_API_KEY, "accept": "audio/mpeg"},
                json=body,
            )
    except httpx.HTTPError as e:
        raise TTSError(f"ElevenLabs request failed: {e.__class__.__name__}") from e
    if r.status_code != 200 or not r.content:
        raise TTSError(f"ElevenLabs returned {r.status_code}")
    return r.content


async def filler() -> bytes:
    """Cached "One sec, let me check." mp3 (in memory, created lazily)."""
    global _filler
    if _filler is None:
        async with _filler_lock:
            if _filler is None:
                _filler = await synthesize(FILLER_TEXT)
    return _filler


async def warm_filler() -> None:
    """Startup warm-up, only with a key; never raises."""
    if not get_settings().ELEVENLABS_API_KEY:
        return
    try:
        await filler()
    except Exception as e:
        log.warning("filler warm-up failed: %s", e)


def reset_filler() -> None:
    global _filler
    _filler = None

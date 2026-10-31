import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app import agent_voice, db, hub, meetings, speech, tts, webhooks_recall


@asynccontextmanager
async def lifespan(app: FastAPI):
    warm = asyncio.create_task(tts.warm_filler())  # no-op without ELEVENLABS_API_KEY
    try:
        async with db.lifespan(app):
            yield
    finally:
        warm.cancel()


app = FastAPI(title="Call Crew", lifespan=lifespan)
meetings.install_error_handlers(app)
app.include_router(meetings.router)
app.include_router(webhooks_recall.router)
app.include_router(hub.router)
app.include_router(agent_voice.router)
app.include_router(speech.router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}

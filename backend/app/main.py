import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import (
    agent_voice,
    chat,
    db,
    debug,
    escalation,
    hub,
    kb,
    llm,
    meetings,
    runtime,
    settings_api,
    speech,
    tts,
    web_ui,
    webhooks_recall,
    webhooks_slack,
)
from app.config import get_settings
from app.notifier import slack as _slack  # noqa: F401  registers the "slack" notifier

# app.* INFO lines (e.g. the orchestrator latency log) are invisible under uvicorn otherwise.
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    warm = asyncio.create_task(tts.warm_filler())  # no-op without ELEVENLABS_API_KEY
    try:
        async with db.lifespan(app):
            await runtime.load()  # UI-edited settings over env, before anything reads them
            await escalation.seed_experts()
            yield
    finally:
        warm.cancel()
        await llm.close()


app = FastAPI(title="Call Crew", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in get_settings().CORS_ORIGINS.split(",") if o.strip()] or ["*"],
    allow_credentials=False,  # auth is a Bearer header, not cookies
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)
meetings.install_error_handlers(app)
app.include_router(meetings.router)
app.include_router(webhooks_recall.router)
app.include_router(webhooks_slack.router)
app.include_router(kb.router)
app.include_router(chat.router)
app.include_router(hub.router)
app.include_router(agent_voice.router)
app.include_router(speech.router)
app.include_router(settings_api.router)
app.include_router(debug.router)  # HACK: offline escalation driver
web_ui.install(app)  # /ui (built React app) + / -> /ui


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}

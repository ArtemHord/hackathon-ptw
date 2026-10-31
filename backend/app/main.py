from fastapi import FastAPI

from app import db, hub, meetings, webhooks_recall

app = FastAPI(title="Call Crew", lifespan=db.lifespan)
meetings.install_error_handlers(app)
app.include_router(meetings.router)
app.include_router(webhooks_recall.router)
app.include_router(hub.router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}

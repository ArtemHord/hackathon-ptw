from fastapi import FastAPI

from app import db, meetings

app = FastAPI(title="Call Crew", lifespan=db.lifespan)
meetings.install_error_handlers(app)
app.include_router(meetings.router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}

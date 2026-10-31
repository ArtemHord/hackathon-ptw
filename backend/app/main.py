from fastapi import FastAPI

app = FastAPI(title="Call Crew")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}

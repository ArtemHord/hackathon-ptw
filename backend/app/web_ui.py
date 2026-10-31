"""Serves the built web app (backend/web/dist) at /ui. Wire with `web_ui.install(app)`."""

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

DIST = Path(__file__).resolve().parent.parent / "web" / "dist"
NOT_BUILT = "Web UI not built: cd backend/web && npm i && npm run build"
NO_STORE = {"Cache-Control": "no-store"}


class _CachedStatic(StaticFiles):
    async def get_response(self, path, scope):
        resp = await super().get_response(path, scope)
        if resp.status_code == 200:
            resp.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return resp


def _index():
    index = DIST / "index.html"
    if not index.is_file():
        return PlainTextResponse(NOT_BUILT, headers=NO_STORE)
    return FileResponse(index, media_type="text/html", headers=NO_STORE)


def install(app: FastAPI) -> None:
    assets = DIST / "assets"
    if assets.is_dir():
        app.mount("/ui/assets", _CachedStatic(directory=assets), name="ui-assets")

    @app.get("/", include_in_schema=False)
    async def root() -> RedirectResponse:
        return RedirectResponse("/ui")

    @app.get("/ui", include_in_schema=False)
    async def ui_index():
        return _index()

    @app.get("/ui/{path:path}", include_in_schema=False)
    async def ui_path(path: str):
        if path:
            f = (DIST / path).resolve()
            if f.is_file() and DIST.resolve() in f.parents:
                return FileResponse(f, headers=NO_STORE)
        return _index()

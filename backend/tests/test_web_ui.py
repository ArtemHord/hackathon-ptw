from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import web_ui


def make(monkeypatch, tmp_path, built=True):
    if built:
        (tmp_path / "assets").mkdir()
        (tmp_path / "assets" / "app.js").write_text("console.log(1)")
        (tmp_path / "index.html").write_text("<html>CC UI</html>")
        (tmp_path / "favicon.svg").write_text("<svg/>")
    monkeypatch.setattr(web_ui, "DIST", tmp_path)
    app = FastAPI()
    web_ui.install(app)
    return TestClient(app, follow_redirects=False)


def test_index_and_spa_fallback(monkeypatch, tmp_path):
    c = make(monkeypatch, tmp_path)
    for p in ("/ui", "/ui/meetings/m_1"):
        r = c.get(p)
        assert r.status_code == 200 and "CC UI" in r.text
        assert r.headers["cache-control"] == "no-store"


def test_assets_cached_and_root_files(monkeypatch, tmp_path):
    c = make(monkeypatch, tmp_path)
    r = c.get("/ui/assets/app.js")
    assert r.status_code == 200 and "immutable" in r.headers["cache-control"]
    assert c.get("/ui/favicon.svg").text == "<svg/>"
    assert "CC UI" in c.get("/ui/%2e%2e/%2e%2e/etc/passwd").text


def test_root_redirects(monkeypatch, tmp_path):
    r = make(monkeypatch, tmp_path).get("/")
    assert r.status_code in (302, 307) and r.headers["location"] == "/ui"


def test_not_built(monkeypatch, tmp_path):
    r = make(monkeypatch, tmp_path, built=False).get("/ui")
    assert r.status_code == 200 and "Web UI not built" in r.text

import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "migrate", Path(__file__).resolve().parents[2] / "scripts" / "migrate.py"
)
migrate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(migrate)


def test_split_ssl_none():
    url, s = migrate.split_ssl("postgresql://u:p@localhost:5432/db")
    assert url.endswith("/db") and s is None


def test_split_ssl_require():
    url, s = migrate.split_ssl("postgresql://u:p@h/db?sslmode=require")
    assert "sslmode" not in url and s is not None and s is not False


def test_split_ssl_disable():
    assert migrate.split_ssl("postgresql://u@h/db?sslmode=disable")[1] is False


def test_migrations_exist():
    assert (migrate.MIGRATIONS_DIR / "001_init.sql").exists()

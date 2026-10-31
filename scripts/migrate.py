"""Apply backend/migrations/*.sql in name order. Usage: cd backend && uv run python ../scripts/migrate.py"""

import asyncio
import os
import ssl
import sys
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import asyncpg

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "backend" / "migrations"


def get_database_url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        sys.path.insert(0, str(MIGRATIONS_DIR.parent))
        from app.config import get_settings

        url = get_settings().DATABASE_URL
    return url


def split_ssl(url: str) -> tuple[str, object]:
    """Return (url without sslmode, ssl arg for asyncpg)."""
    parts = urlsplit(url)
    query = parse_qsl(parts.query)
    mode = next((v for k, v in query if k == "sslmode"), None)
    rest = [(k, v) for k, v in query if k != "sslmode"]
    clean = urlunsplit(parts._replace(query=urlencode(rest)))
    if mode in (None, "disable", "allow", "prefer"):
        return clean, (False if mode in ("disable", "allow") else None)
    ctx = ssl.create_default_context()
    if mode in ("require", "verify-ca"):
        # HACK: Supabase pooler cert chain; encrypt without verification for require.
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    return clean, ctx


async def run() -> int:
    url = get_database_url()
    if not url:
        print("DATABASE_URL is not set", file=sys.stderr)
        return 1
    clean, ssl_arg = split_ssl(url)
    kwargs = {"statement_cache_size": 0}
    if ssl_arg is not None:
        kwargs["ssl"] = ssl_arg
    try:
        conn = await asyncpg.connect(clean, **kwargs)
    except Exception as e:
        print(f"connect failed: {type(e).__name__}", file=sys.stderr)
        return 1
    try:
        await conn.execute(
            "create table if not exists schema_migrations ("
            "name text primary key, applied_at timestamptz not null default now())"
        )
        done = {r["name"] for r in await conn.fetch("select name from schema_migrations")}
        for f in sorted(MIGRATIONS_DIR.glob("*.sql")):
            if f.name in done:
                print(f"skipped {f.name}")
                continue
            async with conn.transaction():
                await conn.execute(f.read_text())
                await conn.execute("insert into schema_migrations(name) values($1)", f.name)
            print(f"applied {f.name}")
    finally:
        await conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))

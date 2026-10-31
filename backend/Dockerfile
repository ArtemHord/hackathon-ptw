FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

# Layer-cached dependencies
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

# NEEDS: agent-page served from backend/ (M2.1)
# App code (+ migrations/, seed/ if present), filtered by .dockerignore
COPY . .

EXPOSE 8000
CMD uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --no-access-log

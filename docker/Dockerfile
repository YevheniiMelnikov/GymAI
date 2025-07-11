# ───────────────────────── base image ─────────────────────────
FROM python:3.12-slim

# ───────────────────────── env vars ───────────────────────────
ENV \
  UV_CACHE_DIR=/root/.cache/uv \
  PYTHONDONTWRITEBYTECODE=1 \
  PYTHONUNBUFFERED=1 \
  PYTHONPATH=/app:/app

ARG PG_MAJOR=17

# ─────────────────── system & build deps ──────────────────────
RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends gnupg curl ca-certificates; \
    \
    CODENAME="$(. /etc/os-release && echo "$VERSION_CODENAME")"; \
    echo "deb [signed-by=/usr/share/keyrings/pgdg.gpg] https://apt.postgresql.org/pub/repos/apt ${CODENAME}-pgdg main" \
      > /etc/apt/sources.list.d/pgdg.list; \
    curl -sSL https://www.postgresql.org/media/keys/ACCC4CF8.asc | gpg --dearmor -o /usr/share/keyrings/pgdg.gpg; \
    \
    apt-get update; \
    apt-get install -y --no-install-recommends \
        git gcc g++ build-essential \
        libopenblas-dev liblapack-dev libatlas-base-dev \
        libffi-dev libpq-dev \
        postgresql-client-${PG_MAJOR} \
        redis-tools; \
    \
    apt-get purge -y --auto-remove gnupg; \
    rm -rf /var/lib/apt/lists/*

# ──────────────────────── uv installer ────────────────────────
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# ─────────────────────────── user ─────────────────────────────
RUN groupadd -g 1000 appgroup && useradd -u 1000 -g appgroup -m appuser

# ─────────────────────── Python deps ──────────────────────────
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv pip install --system .

# Create writable logs directory for Cognee
RUN mkdir -p /usr/local/lib/python3.12/site-packages/logs \
    && chown appuser:appgroup /usr/local/lib/python3.12/site-packages/logs

# ─────────────────────── project code ─────────────────────────
COPY . .

RUN chown -R appuser:appgroup /app
USER appuser

# ───────────────────────── entrypoint ─────────────────────────
ENTRYPOINT ["/bin/sh", "-c"]
CMD [ \
  # → Alembic-миграции в Postgres 17 (URL берётся из env-файла)
  "alembic upgrade head && \
   python -u /app/bot/main.py" \
]

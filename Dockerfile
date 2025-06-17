FROM python:3.13-slim

ENV UV_CACHE_DIR=/root/.cache/uv \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app:/app

ARG PG_MAJOR=17

RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends gnupg curl ca-certificates; \
    \
    CODENAME="$(. /etc/os-release && echo "$VERSION_CODENAME")"; \
    \
    echo "deb [signed-by=/usr/share/keyrings/pgdg.gpg] https://apt.postgresql.org/pub/repos/apt ${CODENAME}-pgdg main" \
      > /etc/apt/sources.list.d/pgdg.list; \
    curl -sSL https://www.postgresql.org/media/keys/ACCC4CF8.asc | gpg --dearmor -o /usr/share/keyrings/pgdg.gpg; \
    \
    apt-get update; \
    apt-get install -y --no-install-recommends \
        git gcc libpq-dev \
        postgresql-client-${PG_MAJOR} \
        redis-tools; \
    \
    apt-get purge -y --auto-remove gnupg; \
    rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

RUN groupadd -g 1000 appgroup && useradd -u 1000 -g appgroup -m appuser

WORKDIR /app

COPY pyproject.toml uv.lock ./

RUN uv pip install --system .

COPY . .

RUN chown -R appuser:appgroup /app

USER appuser

CMD ["python", "-u", "/app/bot/main.py"]

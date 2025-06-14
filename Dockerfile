FROM python:3.13-slim

ENV UV_CACHE_DIR=/root/.cache/uv
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app:/app

RUN apt-get update && apt-get install -y --no-install-recommends \
    git gcc libpq-dev curl postgresql-client && \
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

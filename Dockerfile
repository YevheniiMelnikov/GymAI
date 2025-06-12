FROM python:3.13-slim

ENV UV_CACHE_DIR=/root/.cache/uv
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app:/app

RUN apt-get update && apt-get install -y --no-install-recommends \
    git gcc libpq-dev curl && \
    rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

COPY pyproject.toml uv.lock ./

ARG EXTRAS=""
RUN if [ -n "$EXTRAS" ]; then \
      uv pip install --system ".[${EXTRAS}]"; \
    else \
      uv pip install --system .; \
    fi

COPY . .

CMD ["python", "-u", "/app/bot/main.py"]

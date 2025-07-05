FROM python:3.13-slim

ENV UV_CACHE_DIR=/root/.cache/uv
ARG INSTALL_DEV=false
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    git gcc libpq-dev curl && \
    rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

COPY pyproject.toml uv.lock /app/
WORKDIR /app
RUN if [ "$INSTALL_DEV" = "true" ]; then \
      uv pip install --system ".[dev]"; \
    else \
      uv pip install --system .; \
    fi

COPY . /app

COPY docker/entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

ENTRYPOINT ["/app/entrypoint.sh"]

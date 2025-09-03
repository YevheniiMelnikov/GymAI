# syntax=docker/dockerfile:1.7

FROM python:3.12-slim AS py-base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    UV_SYSTEM_PYTHON=1
WORKDIR /app

FROM ghcr.io/astral-sh/uv:0.4.20 AS uvbin

FROM node:20-alpine AS webbuild
WORKDIR /app/apps/webapp
COPY apps/webapp/package*.json ./
RUN --mount=type=cache,target=/root/.npm npm ci
COPY apps/webapp/frontend ./frontend
COPY apps/webapp/static ./static
RUN npm run build \
 && echo "== build output in ./static ==" \
 && ls -la ./static ./static/js || true \
 && test -f ./static/js/index.js || (echo 'ERROR: ./static/js/index.js not found' && exit 1)

FROM py-base AS deps-app
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && apt-get install -y --no-install-recommends curl libpq5 && rm -rf /var/lib/apt/lists/*
COPY --from=uvbin /uv /usr/local/bin/uv
ARG EXTRAS=""
ARG INSTALL_DEV="false"
COPY pyproject.toml ./
RUN --mount=type=cache,target=/root/.cache/uv bash -lc '\
    EXTLIST="$EXTRAS"; \
    if [ "$INSTALL_DEV" = "true" ]; then \
      if [ -n "$EXTLIST" ]; then EXTLIST="$EXTLIST,dev"; else EXTLIST="dev"; fi; \
    fi; \
    if [ -n "$EXTLIST" ]; then PKG=".[${EXTLIST}]"; else PKG="."; fi; \
    uv pip install --system "$PKG" \
  '

FROM py-base AS deps-coach
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && apt-get install -y --no-install-recommends git gcc g++ build-essential libpq-dev && rm -rf /var/lib/apt/lists/*
COPY --from=uvbin /uv /usr/local/bin/uv
ARG EXTRAS="coach"
ARG INSTALL_DEV="false"
COPY pyproject.toml ./
RUN --mount=type=cache,target=/root/.cache/uv bash -lc '\
    EXTLIST="$EXTRAS"; \
    if [ "$INSTALL_DEV" = "true" ]; then EXTLIST="$EXTLIST,dev"; fi; \
    uv pip install --system ".[$EXTLIST]" \
  '

FROM py-base AS py-runtime
COPY --from=deps-app /usr/local /usr/local
COPY . /app
RUN chmod 0755 /app/docker/entrypoint.sh \
 && sed -i 's/\r$//' /app/docker/entrypoint.sh \
 && apt-get update \
 && apt-get install -y --no-install-recommends curl libpq5 \
 && rm -rf /var/lib/apt/lists/*
ENTRYPOINT ["/app/docker/entrypoint.sh"]

FROM py-runtime AS api-runtime
COPY --from=webbuild /app/apps/webapp/static /app/apps/webapp/static
ENTRYPOINT ["/app/docker/entrypoint.sh"]

FROM py-base AS coach-runtime
COPY --from=deps-coach /usr/local /usr/local
COPY . /app
RUN chmod 0755 /app/docker/entrypoint.sh \
 && sed -i 's/\r$//' /app/docker/entrypoint.sh \
 && apt-get update \
 && apt-get install -y --no-install-recommends curl libpq5 \
 && rm -rf /var/lib/apt/lists/*
ENTRYPOINT ["/app/docker/entrypoint.sh"]

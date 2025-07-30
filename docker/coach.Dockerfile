FROM python:3.12-slim

ENV UV_CACHE_DIR=/root/.cache/uv
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends git gcc curl build-essential python3-dev && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

COPY pyproject.toml uv.lock /app/
WORKDIR /app
RUN uv pip install --system .

RUN mkdir -p /usr/local/lib/python3.12/site-packages/logs && chown 1000:1000 /usr/local/lib/python3.12/site-packages/logs

COPY . /app

CMD ["uvicorn", "ai_coach.api:app", "--host", "0.0.0.0", "--port", "9000"]

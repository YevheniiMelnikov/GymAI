# GymBot

GymBot is a Dockerized platform that includes a Telegram bot (aiogram), API (Django) and AI coach (FastAPI). The project relies on Uvicorn, Redis, and PostgreSQL and uses `uv` and `Taskfile` for dependency management and common tasks.

---

## Features

* Django API with admin panel
* Telegram bot based on `aiogram`
* Redis and PostgreSQL for data and caching
* ASGI server (`uvicorn`)
* Reverse proxy via Nginx with HTTPS
* Ready for Docker deployment

---

## Architecture Overview

**Components**

* **API** (Django ASGI, Uvicorn) – business logic, admin, webapp, REST endpoints under `/api/v1/`.
* **Bot** (aiogram + aiohttp) – webhook server, communicates with API and Redis.
* **AI Coach** (FastAPI) – Cognee-powered retrieval + generation.
* **Celery + Beat** – background jobs and schedules.
* **Redis** – cache, queues, idempotency.
* **PostgreSQL (+pgvector)** – relational storage and vector embeddings.
* **Nginx** – reverse proxy and TLS termination.

**Key directories**

* `apps/` – Django apps (profiles, payments, workout\_plans, webapp, etc.)
* `bot/` – Telegram bot handlers, texts, keyboards, middlewares, utilities
* `core/` – shared cache, services, schemas, enums, tasks
* `ai_coach/` – AI coach service and knowledge integrations
* `config/` – Django settings, URL routing, app settings
* `docker/` – Dockerfiles, compose files, Nginx and Redis configs, environment files

---

## Requirements

* Docker and Docker Compose
* Python 3.12 (>=3.12, <3.13) for running without containers

---

## Installation

1. Copy the example environment file from the `docker` directory and adjust it:

   ```bash
   cp docker/.env.example docker/.env
   ```

2. Set `Required` ENV's (see section `Configuration` below).

3. Place Google service account credentials at the project root:

   * Put `google_creds.json` in the repository root (same level as `docker/`).
   * The file will be bind-mounted into containers at `/app/google_creds.json` and referenced via `GOOGLE_APPLICATION_CREDENTIALS`.

4. Build and run the services (locally):

   ```bash
   task localrun
   ```

   Or manually:

   ```bash
   docker compose -f docker/docker-compose.yml up --build
   ```

---

## Bot

Sources are located in `bot/` with the entrypoint `bot/main.py`.

Local development options:

* With Docker Compose (recommended for API/DB/Redis): `task localrun` starts Postgres, Redis, API, local Nginx on [http://localhost:9090](http://localhost:9090), and the Cloudflare tunnel service.
* Run the bot locally from your IDE or terminal:

  * Ensure Redis and API are up (via `task localrun`).
  * Start the bot: `uv run python -m bot.main`.
  * Local Nginx forwards webhooks to `host.docker.internal:8088` as configured in `docker/nginx.local.conf`.
  * Expose the local stack to Telegram via the bundled Cloudflare tunnel. Provide `CF_TUNNEL_TOKEN` in `docker/.env`; `task localrun` (or `docker compose -f docker/docker-compose-local.yml up cloudflared`) will launch the `cloudflared` service and publish a public URL accessible through Cloudflare Zero Trust. Use that URL as `WEBHOOK_HOST`.

> To run bot locally FULLY with docker set `DOCKER_BOT_START=true`

---

## API

The Django API is served by `uvicorn`.

**Local URLs**

* Admin panel (via API directly): [http://localhost:8000/admin/](http://localhost:8000/admin/)
* Admin panel (via local Nginx proxy): [http://localhost:9090/admin/](http://localhost:9090/admin/)
* Healthcheck: [http://localhost:8000/health/](http://localhost:8000/health/)

**Production (behind Nginx)**

* Admin panel: `https://<your-domain>/admin/`
* Healthcheck: `https://<your-domain>/health/`

Use the credentials from `docker/.env` (`DJANGO_ADMIN` / `DJANGO_PASSWORD`) to access the admin interface.

---

## AI Coach API

FastAPI service under `/ask/`.

### Request

```json
{
  "client_id": 1,
  "prompt": "text",
  "mode": "program | subscription | update | ask_ai",
  "period": "1m",
  "workout_days": ["Mon"],
  "expected_workout": "...",
  "feedback": "..."
}
```

### Response

* `mode=program` or `mode=update` → `Program`.
* `mode=subscription` → `Subscription`.
* `mode=ask_ai` → `QAResponse` `{ "answer": str, "sources": [str, ...] }`.


**ask\_ai response example**

```json
{
  "answer": "Drink water and rest between sets.",
  "sources": [
    "client: last session notes",
    "global: hydration guidelines"
  ]
}
```

---

## Redis

Redis runs with `appendonly.aof` and LRU eviction. Configuration is stored in `docker/redis.conf`.

---

## Celery

Background tasks are processed by Celery workers. Docker Compose includes two services (`celery` and `beat`) for this purpose. When running the worker outside of Docker make sure Redis is reachable and update the `REDIS_URL` in your `docker/.env` file accordingly. You may also need to set `BOT_INTERNAL_URL` so Celery can reach the bot API.

```bash
PYTHONPATH=. celery -A config.celery:celery_app worker \
    -l info -Q default,maintenance -P threads
```

If Celery prints connection errors such as `Error -2 connecting to redis:6379`, verify that `REDIS_URL` points to your local Redis instance.

### Scheduled tasks

| Task                               | Schedule                           | Purpose                                           |
| ---------------------------------- | ---------------------------------- | ------------------------------------------------- |
| `pg_backup`                        | daily 02:00                        | dump Postgres database                            |
| `redis_backup`                     | daily 02:01                        | export Redis data                                 |
| `cleanup_backups`                  | daily 02:02                        | remove backups older than `BACKUP_RETENTION_DAYS` |
| `deactivate_expired_subscriptions` | daily 01:00                        | disable subscriptions past end date               |
| `warn_low_credits`                 | daily 00:00                        | notify clients with insufficient credits          |
| `charge_due_subscriptions`         | daily 00:30                        | deduct credits for active plans                   |
| `send_daily_survey`                | daily 09:00                        | trigger workout feedback survey                   |
| `refresh_external_knowledge`       | every `KNOWLEDGE_REFRESH_INTERVAL` | rebuild AI coach knowledge                        |
| `prune_cognee`                     | daily 02:10                        | clear cached Cognee data                          |

---

## AI Coach and Knowledge Base

The project ships an AI coach backed by Cognee. Each client and chat is mapped to datasets named `client_<id>_message`. Chat entries are stored with a `user:` or `bot:` prefix so Cognee keeps the full dialog history. SHA‑256 hashes are cached in Redis with a TTL derived from `BACKUP_RETENTION_DAYS` to prevent repeat ingestion. New texts are ingested asynchronously and cognified before they are searchable.

To refresh external knowledge (e.g., documents from Google Drive), Celery calls `refresh_external_knowledge` every `KNOWLEDGE_REFRESH_INTERVAL` seconds. The task sends an authenticated request to the AI coach, which in turn runs `KnowledgeBase.refresh()`.

**Key settings**

* `KNOWLEDGE_REFRESH_INTERVAL` – periodic rebuild interval in seconds
* `AI_COACH_TIMEOUT` – timeout for HTTP calls to the AI coach

**Other maintenance**

* `BACKUP_RETENTION_DAYS` – retention period for Postgres and Redis backups

---

## Database Migrations

Run inside Docker (API container):

```bash
task migrate
```

This will run `makemigrations` and `migrate`.

---

## Tests

Run tests with:

```bash
uv run pytest -q
```

---

## Taskfile Commands

The project includes a [Taskfile](https://taskfile.dev/) for convenience.

**Common commands**

| Command      | Description                        |
| ------------ | ---------------------------------- |
| `run`        | Start all services with Docker     |
| `localrun`   | Local development environment      |
| `test`       | Run tests                          |
| `lint`       | Lint the codebase (ruff + pyrefly) |
| `format`     | Format the codebase                |
| `update`     | Update dependencies                |
| `pre-commit` | Run all pre-commit hooks           |

Example:

```bash
task lint
```

---

## Pre-Commit

**Installed hooks**

* `ruff` for formatting and linting
* `mypy` for static type checking
* `pytest` for running tests
* `uv-lock` to check the lock file
* Basic hooks: `check-yaml`, `trailing-whitespace`, `end-of-file-fixer`

**Install hooks**

```bash
uv run pre-commit install
```

**Run manually**

```bash
task pre-commit
```

---

## Production Deployment

```bash
docker compose -f docker/docker-compose.yml up -d --build
```

Verify the service is available via Nginx:

```bash
curl http://localhost/health/
```

---

## Nginx

Nginx acts as a reverse proxy with HTTPS (Let's Encrypt) and routes requests:

* `/static/` → Django static files
* `/api/` → API server
* `/` → Telegram bot

See `docker/nginx.conf` for configuration. Rebuild the image to apply changes:

```bash
docker compose -f docker/docker-compose.yml up -d --build nginx
```

---

## Configuration (docker/.env)

Create `docker/.env` from `docker/.env.example` and set the following minimum variables for development:

**Required**

* `SECRET_KEY` – Django secret key
* `API_KEY` – internal API key for bot/API communication (generate from Django container)
* `BOT_TOKEN` – Telegram bot token
* `WEBHOOK_HOST` – base URL for webhooks (e.g., `http://localhost:9090` for local Nginx)
* `CF_TUNNEL_TOKEN` – Cloudflare Zero Trust token for the bundled `cloudflared` tunnel service

> **Important:** To enable Google services (Sheets/Drive/Docs), you **must** place a file named `google_creds.json` at the **project root**. This file is bind-mounted into containers at `/app/google_creds.json` and should be referenced by `GOOGLE_APPLICATION_CREDENTIALS`.

**Common optional settings (sensible defaults exist)**

* `REDIS_URL` (default: `redis://redis:6379`)
* `ALLOWED_HOSTS` (comma-separated or JSON list)
* `DJANGO_ADMIN` / `DJANGO_PASSWORD` (admin credentials)
* `AI_COACH_URL` (default: `http://ai_coach:9000/`)
* `KNOWLEDGE_REFRESH_INTERVAL`, `BACKUP_RETENTION_DAYS`
* `PAYMENT_*` (provider keys and callback URL)

`WEBHOOK_URL` is auto-derived as `${WEBHOOK_HOST}${WEBHOOK_PATH}` unless explicitly set. See `config/app_settings.py` for all available options.

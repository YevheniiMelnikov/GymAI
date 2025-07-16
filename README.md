# GymBot

GymBot is a Dockerized platform that connects a Telegram bot with a Django API. The project relies on Uvicorn, Redis and PostgreSQL and uses `uv` and `Taskfile` for dependency management and common tasks.

---

## Features

- Django API with documentation and admin panel
- Telegram bot based on `aiogram`
- Redis and PostgreSQL for data storage
- ASGI server (`uvicorn`)
- Reverse proxy via Nginx with HTTPS
- Ready for Docker deployment

---

## Requirements

- Docker and Docker Compose
- Python 3.13+ (for running without containers)

---

## Installation

1. Copy the example environment file and adjust it:

   ```bash
   cp .env.example .env
   ```

2. Build and run the services:

   ```bash
   task run
   ```

   Or manually:

   ```bash
   docker compose -f docker/docker-compose.yml up --build
   ```

---

## Bot

The bot runs in a separate container.
Sources are located in `bot/` with the entrypoint `bot/main.py`.

---

## API

The Django API is served by `uvicorn`.

- Admin panel: [http://localhost:8080/admin/](http://localhost:8080/admin/)
- API schema: [http://localhost:8080/api/schema/swagger-ui/](http://localhost:8080/api/schema/swagger-ui/)
- Healthcheck: [http://localhost:8000/health/](http://localhost:8000/health/)

Use the credentials from `.env` (`DJANGO_ADMIN` / `DJANGO_PASSWORD`) to access the admin interface.

---

## Redis

Redis runs with `appendonly.aof` and LRU eviction. Configuration is stored in `docker/redis.conf`.

---

## Celery

Background tasks are processed by Celery workers. Docker Compose includes two
services (`celery` and `beat`) for this purpose. When running the worker outside
of Docker make sure Redis is reachable and update the `REDIS_URL` in your `.env`
file accordingly. You may also need to set `BOT_INTERNAL_URL` so Celery can
reach the bot API.

```bash
PYTHONPATH=. celery -A config.celery:celery_app worker \
    -l info -Q default,maintenance -P threads
```

If Celery prints connection errors such as `Error -2 connecting to redis:6379`,
verify that `REDIS_URL` points to your local Redis instance.

---

## Tests

Run tests with:

```bash
uv run pytest -q
```

---

## Taskfile commands

The project includes a [Taskfile](https://taskfile.dev/) for convenience.
Common commands:

| Command    | Description                                  |
|------------|----------------------------------------------|
| `run`      | Start all services with Docker               |
| `localrun` | Local development environment                |
| `test`     | Run tests                                     |
| `lint`     | Lint the codebase (ruff + mypy)               |
| `format`   | Format the codebase                           |
| `update`   | Update dependencies                           |
| `pre-commit` | Run all pre-commit hooks                    |

Example:

```bash
task lint
```

---

## Pre-Commit

Installed hooks:

- `ruff` for formatting and linting
- `mypy` for static type checking
- `pytest` for running tests
- `uv-lock` to check the lock file
- Basic hooks: `check-yaml`, `trailing-whitespace`, `end-of-file-fixer`

Install hooks:

```bash
uv run pre-commit install
```

Run them manually:

```bash
task pre-commit
```

---

## Production deployment

```bash
docker compose -f docker/docker-compose.yml up -d --build
```

Verify the API is available:

```bash
curl http://localhost:8000/health/
```

---

## Nginx

Nginx acts as a reverse proxy with HTTPS (Let's Encrypt) and routes requests:

- `/static/` → Django static files
- `/api/` → API server
- `/` → Telegram bot

See `docker/nginx.conf` for configuration. Rebuild the image to apply changes:

```bash
docker compose -f docker/docker-compose.yml up -d --build nginx
```

## Global system prompt

The system instruction used by Cognee is loaded from `./core/ai_coach/global_system_prompt.txt`.
This path is assigned to the `GRAPH_PROMPT_PATH` environment variable automatically on startup, but you can override it if needed.
Make sure this file exists before starting the services.

### Cognee access control

If you don't need multi-tenant dataset permissions, disable Cognee ACL by setting
`ENABLE_BACKEND_ACCESS_CONTROL=False` in your `.env` file. When enabled, dataset
names include the Cognee user ID to avoid permission errors.

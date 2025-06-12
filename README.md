# GymBot

GymBot is a platform that connects a Telegram bot with a Django API. The project uses Docker, Uvicorn, Redis and PostgreSQL. The whole setup follows best practices with `uv`, a Taskfile for handy commands, pre-commit hooks and strict typing.

---

## 🚀 Features

- Django API with documentation and admin panel
- Telegram bot powered by `aiogram`
- Communication through Redis and PostgreSQL
- ASGI server via `uvicorn`
- Reverse proxy with Nginx (HTTPS)
- Fully dockerized environment
- Redis tuned with AOF and LRU

---

## 🧰 Requirements

- Docker
- Docker Compose
- Python 3.13+ (for running without containers)

---

## 🛠 Installation & Run

1. Create an environment file:

   ```bash
   cp .env.example .env
   ```

2. Build and start the services:

   ```bash
   task run
   ```

   or manually:

   ```bash
   docker compose up --build
   ```

---

## 🤖 Bot

The bot runs in a dedicated container.

- Sources: `bot/`
- Entry point: `bot/main.py`
- Backups mounted from `dumps/`

---

## 🌐 API

The Django ASGI app runs under `uvicorn`.

- Admin: <http://localhost:8080/admin/>
- Default credentials are read from `.env` (`DJANGO_USER` and `DJANGO_PASSWORD`)
- Docs: <http://localhost:8080/api/schema/swagger-ui/>
- Healthcheck: <http://localhost:8000/health/>

---

## 🔁 Redis

Redis is configured with `appendonly.aof`, `maxmemory 256mb`, `allkeys-lru`.

- Config: `redis.conf`
- Storage: `redisdata` volume

---

## 🧪 Tests

```bash
task test
```

Or manually:

```bash
uv run pytest
```

---

## 🧱 Taskfile commands

This project uses [Taskfile](https://taskfile.dev/) for convenience.

| Command    | Description                                    |
|------------|------------------------------------------------|
| run        | Run all services via Docker                    |
| localrun   | Local development with `docker-compose-local.yml` |
| test       | Run tests                                      |
| lint       | Run linter (ruff + pyrefly)                    |
| format     | Format code                                    |
| update     | Update dependencies                            |
| pre-commit | Run all hooks                                  |

Example:

```bash
task lint
```

---

## 🧹 Pre-Commit

Installed hooks:

- `ruff` — autoformat and lint
- `mypy` — static type check
- `pytest` — run tests
- `uv-lock` — lock file control
- basic hooks: `check-yaml`, `trailing-whitespace`, `end-of-file-fixer`

Install hooks:

```bash
uv run pre-commit install
```

Run manually:

```bash
task pre-commit
```

---

## 🚀 Production deploy

```bash
docker compose -f docker-compose.yml up -d --build
```

Check availability:

```bash
curl http://localhost:8000/health/
```

---

## 🔐 Nginx

The reverse proxy works with HTTPS (Let's Encrypt) and routes:

- `/static/` → Django static
- `/api/` → API server
- `/` → Telegram bot

Config file: `nginx.conf`

After editing the config, rebuild the image and restart:

```bash
docker compose up -d --build nginx
```

---

## 📦 Versioning

The project uses `bumpversion` for releases. The current version is stored in `bot/VERSION` and `pyproject.toml`.


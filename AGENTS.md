# GymBot Agent Guidelines

## Mission And Context
Deliver production-grade improvements to GymBot's multi-service stack (Django API, aiogram bot, FastAPI AI coach, Celery workers, infrastructure) without breaking cross-service contracts. Every change must respect component boundaries and keep deployments reproducible.

## Architecture Awareness
- `apps/` — Django applications with business logic, admin customisations, and REST/web views. Use service functions or typed repositories; never call them straight from the bot.
- `bot/` — aiogram handlers, states, middlewares, and Telegram-specific utilities. Isolate bot concerns here and talk to the API through typed clients.
- `ai_coach/` — FastAPI service for Cognee-backed retrieval and generation. Keep prompt templates and retrieval pipelines cohesive and settings-driven.
- `core/` — Shared services, cache helpers, enums, and Celery tasks. Do not leak bot- or Django-specific types into generic utilities.
- `config/` and `docker/` — Settings, environment wiring, and deployment assets. Never hardcode secrets; rely on `pydantic-settings`.
- Prefer grouping helper utilities into dedicated modules or utility packages instead of scattering ad-hoc functions across handlers; keep the handler modules focused on routing and glue logic.

## Engineering Principles
- Target Python 3.12 with full type annotations. Define `TypedDict`/`Protocol` interfaces instead of passing `dict` or `Any`.
- Comments and log messages stay in English; communicate with the maintainer in Russian.
- Forbid `from __future__ import annotations` and other unnecessary compatibility shims.
- All configuration flows through `pydantic-settings`. Represent defaults explicitly and source values from environment variables.
- Prefer `pathlib.Path`, context managers from `contextlib`, and f-strings. Avoid ad-hoc helpers and hidden singletons; keep modules cohesive.
- Honour asynchronous boundaries: await Django async ORM, aiogram, and aiohttp calls and push CPU-bound work into Celery tasks.

## Implementation Workflow
1. Clarify the behaviour you are touching by surveying the relevant module (`README.md`, services, tests, settings) and tracing the API/bot flow end-to-end.
2. Shape the change with explicit dependencies. Inject settings or typed models instead of importing global state, and keep cross-service contracts backward compatible.
3. Write code that explains itself. Add lightweight docstrings only when behaviour is non-obvious; focus on the why.
4. Keep migrations, fixtures, and translations aligned. If data models change, wrap them with migrations or document the manual steps.

## Testing Policy
- Add or update tests only when a change touches critical paths (auth flows, payments, subscription lifecycle, workout plan generation, AI coach reasoning, Celery scheduling). Keep them targeted and deterministic. Do not create more than 2 tests per task.
- Honour existing tests even if the module is low priority. Adjust them when behaviour legitimately changes.

## Quality Gates
- Run `task format` whenever code layout changes.
- Always use f-strings instead of "%s" or .format()
- Run `task format` after every task.
- Document any required env vars, migrations, or background services in the review summary when they affect the change.

## Task Command Handling
- When invoking `task` or `uv` commands locally, always set `UV_CACHE_DIR` (or `XDG_CACHE_HOME`) to a directory you own, e.g. `UV_CACHE_DIR=/tmp/uv-cache-<your-username> task format`, so the cache stays outside the repo/host `~/.cache` and avoids permission issues. Do not modify the Taskfile for this; wrap commands with the environment variable instead.

## Code Review Checklist
- Full type hints, no `Any` leaks in public APIs, and cohesive module boundaries.
- Comments/docstrings in English, communication in Russian, and no TODO/FIXME leftovers.
- No premature abstractions or one-off helpers. Prefer direct, readable code with clear dependencies.
- Verify that Celery schedules, bot webhooks, and API endpoints keep their contracts. Flag risky assumptions explicitly in the review summary.

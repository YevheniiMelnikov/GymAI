# Evals

This directory contains integration eval runners.

## Ask AI evals

The Ask AI eval is an integration quality test for the `ask_ai` mode. It runs against the local Docker
stack (API + AI Coach + KB) and calls the AI Coach over HTTP.

Pipeline:

```
Profile (Postgres) → sync_profile_dataset → AI Coach HTTP → KB → Agent → Answer → LLM Judge → Report
```

### Scenarios (fixtures)

We use **scenarios**. Each scenario is a pair of `profile.json` + `cases.yaml`:

```
evals/ask_ai/fixtures/scenarios/<scenario>/
  profile.json
  cases.yaml
```

### Run

```
task run
task eval
```

**Important:** `task eval` runs **all scenarios** found in `evals/ask_ai/fixtures/scenarios/`.

### Reports

- `evals/ask_ai/reports/latest.md` — last run
- `evals/ask_ai/reports/ask_ai_YYYYMMDD_HHMMSS.md` — timestamped report

### Requirements

- Local Docker stack running (`task run`).
- `AI_COACH_URL` reachable from host (typically `http://localhost:9000`).
- `LLM_API_KEY` configured for the judge.

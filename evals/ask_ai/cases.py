from __future__ import annotations


import yaml

from evals.ask_ai.config import SCENARIOS_DIR
from evals.ask_ai.models import EvalCase


def load_cases(*, scenario: str) -> list[EvalCase]:
    target = SCENARIOS_DIR / scenario / "cases.yaml"
    if not target.exists():
        raise FileNotFoundError(f"scenario_cases_missing:{target}")
    data = yaml.safe_load(target.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise RuntimeError("cases_yaml_invalid")
    cases: list[EvalCase] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        case_id = str(item.get("id") or "").strip()
        question = str(item.get("question") or "").strip()
        if not case_id or not question:
            continue
        tags = list(item.get("tags") or [])
        expectations = dict(item.get("expectations") or {})
        cases.append(
            EvalCase(
                case_id=case_id,
                question=question,
                tags=[str(tag) for tag in tags],
                expectations=expectations,
            )
        )
    return cases

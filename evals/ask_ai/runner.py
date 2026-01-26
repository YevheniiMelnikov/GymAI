from __future__ import annotations
import asyncio
from datetime import datetime
from time import monotonic

from evals.ask_ai import config
from evals.ask_ai.bootstrap import configure_api_service, init_container, setup_django, shutdown_container
from evals.ask_ai.cases import load_cases
from evals.ask_ai.evaluate import evaluate_cases
from evals.ask_ai.knowledge import sync_profile_dataset
from evals.ask_ai.models import EvalCaseResult, EvalRunMeta
from evals.ask_ai.profile import ensure_eval_profile, load_profile_fixture, profile_text
from evals.ask_ai.report import format_results, render_markdown, write_reports


def _build_meta(
    *,
    started_at: datetime,
    duration_s: float,
    profile_id: int | None,
    tg_id: int | None,
    cases_total: int,
    run_error: str | None,
    warnings: list[str] | None,
) -> EvalRunMeta:
    return EvalRunMeta(
        started_at=started_at,
        duration_s=duration_s,
        ai_coach_url=config.ai_coach_url(),
        agent_model=config.agent_model(),
        agent_temperature=config.agent_temperature() or "",
        judge_model=config.judge_model_name(),
        judge_temperature=config.judge_temperature() or "",
        profile_id=profile_id,
        tg_id=tg_id,
        cases_total=cases_total,
        git_commit=config.git_short_hash(),
        run_error=run_error,
        warnings=warnings,
    )


def run_eval(*, scenario: str) -> tuple[int | None, list[EvalCaseResult], list[str]]:
    profile_data = load_profile_fixture(scenario=scenario)
    cases = load_cases(scenario=scenario)
    if not cases:
        raise RuntimeError("no_cases_found")

    warnings: list[str] = []
    container = configure_api_service()
    try:
        asyncio.run(init_container(container))
        profile = ensure_eval_profile(profile_data)
        sync_payload = sync_profile_dataset(profile.id)
        indexed = bool(sync_payload.get("indexed"))
        if not indexed:
            warnings.append(f"profile_not_indexed:{sync_payload}")
        results = asyncio.run(
            evaluate_cases(
                cases=cases,
                profile_id=profile.id,
                profile_text=profile_text(profile_data),
                language=profile_data.get("language"),
            )
        )
        return profile.id, results, warnings
    finally:
        asyncio.run(shutdown_container(container))


def run_cognify_only(*, scenario: str) -> bool:
    profile_data = load_profile_fixture(scenario=scenario)
    container = configure_api_service()
    try:
        asyncio.run(init_container(container))
        profile = ensure_eval_profile(profile_data)
        payload = sync_profile_dataset(profile.id)
        return bool(payload.get("indexed"))
    finally:
        asyncio.run(shutdown_container(container))


def main(command: str = "run") -> int:
    setup_django()
    scenarios = config.list_scenarios()
    if not scenarios:
        print("no_scenarios_found")
        return 2
    if command == "cognify":
        indexed_all = True
        for scenario in scenarios:
            indexed = run_cognify_only(scenario=scenario)
            print(f"cognify_{scenario}={'ok' if indexed else 'failed'}")
            indexed_all = indexed_all and indexed
        return 0 if indexed_all else 1

    started_at = datetime.now()
    started_monotonic = monotonic()
    overall_failed = False
    for scenario in scenarios:
        results: list[EvalCaseResult] = []
        run_error: str | None = None
        warnings: list[str] = []
        profile_id: int | None = None
        try:
            profile_id, results, warnings = run_eval(scenario=scenario)
        except FileNotFoundError as exc:
            run_error = str(exc)
        except Exception as exc:  # noqa: BLE001
            detail = str(exc).strip()
            detail = detail.replace("\n", " ")[:200] if detail else ""
            run_error = f"{type(exc).__name__}: {detail}" if detail else type(exc).__name__

        duration_s = monotonic() - started_monotonic
        profile_data = load_profile_fixture(scenario=scenario) if (config.SCENARIOS_DIR / scenario).exists() else {}
        tg_id = profile_data.get("tg_id") if profile_data else None
        meta = _build_meta(
            started_at=started_at,
            duration_s=duration_s,
            profile_id=profile_id,
            tg_id=tg_id,
            cases_total=len(results),
            run_error=run_error,
            warnings=warnings or None,
        )
        markdown = render_markdown(meta, results)
        stamped_path, latest_path = write_reports(
            config.REPORTS_DIR,
            markdown,
            timestamp=started_at.strftime("%Y%m%d_%H%M%S"),
        )
        print(f"\nScenario: {scenario}")
        print(format_results(results))
        print(f"\nReport: {latest_path}\nReport (timestamped): {stamped_path}")
        if run_error:
            print(f"\nRun error: {run_error}")
        if warnings:
            print(f"\nWarnings: {'; '.join(warnings)}")
        if run_error or any(not result.passed for result in results):
            overall_failed = True

    return 1 if overall_failed else 0

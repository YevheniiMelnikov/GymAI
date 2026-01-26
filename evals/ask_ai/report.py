from __future__ import annotations

from pathlib import Path
from typing import Iterable

from evals.ask_ai.models import EvalCaseResult, EvalRunMeta


def format_results(results: Iterable[EvalCaseResult]) -> str:
    lines: list[str] = []
    passed = 0
    results_list = list(results)
    for result in results_list:
        if result.passed:
            passed += 1
            lines.append(f"PASS {result.case_id}")
            continue
        detail = ", ".join(result.failures)
        preview = f" | {result.answer_preview}" if result.answer_preview else ""
        lines.append(f"FAIL {result.case_id} → {detail}{preview}")
    total = len(results_list)
    failed = total - passed
    lines.append("")
    lines.append("Summary:")
    lines.append(f"  total: {total}")
    lines.append(f"  passed: {passed}")
    lines.append(f"  failed: {failed}")
    return "\n".join(lines)


def _format_table_row(values: list[str]) -> str:
    return "| " + " | ".join(values) + " |"


def _score_value(value: int | None) -> str:
    return "-" if value is None else str(value)


def render_markdown(meta: EvalRunMeta, results: list[EvalCaseResult]) -> str:
    total = len(results)
    passed = sum(1 for result in results if result.passed)
    failed = total - passed
    judge_scores = [result.score for result in results if result.score is not None]
    avg_profile = (
        round(sum(score.profile_alignment for score in judge_scores) / len(judge_scores), 2) if judge_scores else None
    )
    avg_safety = round(sum(score.safety for score in judge_scores) / len(judge_scores), 2) if judge_scores else None
    avg_usefulness = (
        round(sum(score.usefulness for score in judge_scores) / len(judge_scores), 2) if judge_scores else None
    )
    avg_faithfulness = (
        round(sum(score.faithfulness_to_kb for score in judge_scores) / len(judge_scores), 2) if judge_scores else None
    )

    lines: list[str] = ["# Ask AI eval report", ""]
    lines.append("## Run metadata")
    lines.append("")
    lines.append(f"- started_at: {meta.started_at.strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"- ai_coach_url: {meta.ai_coach_url}")
    lines.append(f"- profile_id: {meta.profile_id if meta.profile_id is not None else '-'}")
    lines.append(f"- tg_id: {meta.tg_id if meta.tg_id is not None else '-'}")
    lines.append(f"- cases_total: {meta.cases_total}")
    lines.append(f"- agent_model: {meta.agent_model}")
    lines.append(f"- agent_temperature: {meta.agent_temperature or '-'}")
    lines.append(f"- judge_model: {meta.judge_model}")
    lines.append(f"- judge_temperature: {meta.judge_temperature or '-'}")
    if meta.git_commit:
        lines.append(f"- git_commit: {meta.git_commit}")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- total: {total}")
    lines.append(f"- passed: {passed}")
    lines.append(f"- failed: {failed}")
    lines.append(f"- duration_seconds: {round(meta.duration_s, 2)}")
    if meta.run_error:
        lines.append(f"- run_error: {meta.run_error}")
    if meta.warnings:
        warnings_line = "; ".join(meta.warnings)
        lines.append(f"- warnings: {warnings_line}")
    if judge_scores:
        lines.append("")
        lines.append("## Judge averages")
        lines.append("")
        lines.append(f"- profile_alignment: {avg_profile}")
        lines.append(f"- safety: {avg_safety}")
        lines.append(f"- usefulness: {avg_usefulness}")
        lines.append(f"- faithfulness_to_kb: {avg_faithfulness}")
    lines.append("")
    lines.append("## Cases")
    lines.append("")
    lines.append(_format_table_row(["id", "status", "profile", "safety", "usefulness", "faithfulness", "notes"]))
    lines.append(_format_table_row(["---", "---", "---", "---", "---", "---", "---"]))
    for result in results:
        score = result.score
        notes = ", ".join(result.failures) if result.failures else "-"
        lines.append(
            _format_table_row(
                [
                    result.case_id,
                    "PASS" if result.passed else "FAIL",
                    _score_value(score.profile_alignment if score else None),
                    _score_value(score.safety if score else None),
                    _score_value(score.usefulness if score else None),
                    _score_value(score.faithfulness_to_kb if score else None),
                    notes,
                ]
            )
        )
    lines.append("")
    lines.append("## Case details")
    lines.append("")
    for result in results:
        lines.append(f"## {result.case_id} — {'PASS' if result.passed else 'FAIL'}")
        lines.append("")
        lines.append("**Question**")
        lines.append("")
        lines.append(result.question)
        lines.append("")
        lines.append("**Sources**")
        lines.append("")
        if result.sources:
            for source in result.sources:
                lines.append(f"- {source}")
        else:
            lines.append("- -")
        lines.append("")
        lines.append("**Answer**")
        lines.append("")
        lines.append(result.answer or "-")
        lines.append("")
        lines.append("**Judge**")
        lines.append("")
        if result.score:
            lines.append(
                f"- profile_alignment: {result.score.profile_alignment}\n"
                f"- safety: {result.score.safety}\n"
                f"- usefulness: {result.score.usefulness}\n"
                f"- faithfulness_to_kb: {result.score.faithfulness_to_kb}\n"
                f"- comment: {result.score.comment}"
            )
        else:
            lines.append("- -")
        lines.append("")
        if result.failures or result.error:
            lines.append("**Errors**")
            lines.append("")
            if result.error:
                lines.append(f"- {result.error}")
            for failure in result.failures:
                lines.append(f"- {failure}")
            lines.append("")
    return "\n".join(lines)


def write_reports(report_dir: Path, markdown: str, *, timestamp: str) -> tuple[Path, Path]:
    report_dir.mkdir(parents=True, exist_ok=True)
    stamped_path = report_dir / f"ask_ai_{timestamp}.md"
    latest_path = report_dir / "latest.md"
    stamped_path.write_text(markdown, encoding="utf-8")
    latest_path.write_text(markdown, encoding="utf-8")
    return stamped_path, latest_path

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml
from loguru import logger

TechniqueLanguage = Literal["ru", "ua", "eng"]


@dataclass(frozen=True, slots=True)
class ExerciseTechnique:
    canonical_name: str
    technique_description: tuple[str, ...]


def resolve_technique_language(raw: str | None) -> TechniqueLanguage:
    normalized = str(raw or "").strip().lower()
    if normalized in {"ru", "rus", "russian"}:
        return "ru"
    if normalized in {"ua", "uk", "ukr", "ukrainian"}:
        return "ua"
    if normalized in {"en", "eng", "english"}:
        return "eng"
    return "eng"


def _technique_path(language: TechniqueLanguage) -> Path:
    return Path(__file__).resolve().parent / "technique" / f"{language}.yml"


def _normalize_steps(raw: object) -> tuple[str, ...]:
    if not isinstance(raw, list):
        return tuple()
    steps: list[str] = []
    for item in raw:
        text = str(item or "").strip()
        if text:
            steps.append(text)
    return tuple(steps)


def _normalize_canonical_name(value: object) -> str:
    text = str(value or "").strip()
    return " ".join(text.split()).lower()


@lru_cache(maxsize=3)
def load_technique_catalog(language: TechniqueLanguage) -> dict[str, ExerciseTechnique]:
    path = _technique_path(language)
    if not path.exists():
        logger.warning(f"exercise_technique_missing language={language} path={path}")
        return {}
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"exercise_technique_load_failed language={language} error={exc}")
        return {}
    if not isinstance(raw, dict):
        logger.warning(f"exercise_technique_invalid_root language={language}")
        return {}
    catalog: dict[str, ExerciseTechnique] = {}
    for key, payload in raw.items():
        gif_key = str(key or "").strip().lstrip("/")
        if not gif_key or not isinstance(payload, dict):
            continue
        canonical_name = str(payload.get("canonical_name") or "").strip()
        steps = _normalize_steps(payload.get("technique_description"))
        if not canonical_name and not steps:
            continue
        catalog[gif_key] = ExerciseTechnique(canonical_name=canonical_name, technique_description=steps)
    return catalog


@lru_cache(maxsize=3)
def load_technique_reverse_index(language: TechniqueLanguage) -> dict[str, str]:
    catalog = load_technique_catalog(language)
    reverse: dict[str, str] = {}
    for gif_key, technique in catalog.items():
        normalized = _normalize_canonical_name(technique.canonical_name)
        if not normalized:
            continue
        reverse.setdefault(normalized, gif_key)
    return reverse


def get_exercise_technique(gif_key: str, language: str | None) -> ExerciseTechnique | None:
    safe_key = str(gif_key or "").strip().lstrip("/")
    if not safe_key:
        return None
    resolved = resolve_technique_language(language)
    return load_technique_catalog(resolved).get(safe_key)


def resolve_gif_key_from_canonical_name(name: str, language: str | None) -> str | None:
    normalized = _normalize_canonical_name(name)
    if not normalized:
        return None
    resolved = resolve_technique_language(language)
    return load_technique_reverse_index(resolved).get(normalized)


__all__ = [
    "ExerciseTechnique",
    "TechniqueLanguage",
    "get_exercise_technique",
    "load_technique_catalog",
    "load_technique_reverse_index",
    "resolve_technique_language",
    "resolve_gif_key_from_canonical_name",
]

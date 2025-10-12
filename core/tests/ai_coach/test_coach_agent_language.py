from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType


MODULE_PATH: Path = Path(__file__).resolve().parents[3] / "ai_coach" / "language.py"
SPEC = importlib.util.spec_from_file_location("ai_coach.language", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE: ModuleType = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
resolve_language_name = getattr(MODULE, "resolve_language_name")


def test_lang_maps_ua_to_ukrainian() -> None:
    language: str = resolve_language_name("ua")
    assert language == "Ukrainian"


def test_lang_maps_complex_code_to_ukrainian() -> None:
    language: str = resolve_language_name("uk_UA")
    assert language == "Ukrainian"


def test_lang_returns_original_for_unknown_locale() -> None:
    language: str = resolve_language_name("de")
    assert language == "de"

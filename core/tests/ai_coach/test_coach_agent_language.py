import importlib.util
from pathlib import Path
from types import ModuleType

from ai_coach.agent import AgentDeps, CoachAgent
from config.app_settings import settings


MODULE_PATH: Path = Path(__file__).resolve().parents[3] / "ai_coach" / "utils.py"
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


def test_agent_lang_returns_locale_code() -> None:
    deps = AgentDeps(client_id=1, locale="ru")
    assert CoachAgent._lang(deps) == "ru"


def test_agent_lang_uses_default_when_missing() -> None:
    deps = AgentDeps(client_id=2, locale=None)
    assert CoachAgent._lang(deps) == settings.DEFAULT_LANG


def test_language_context_returns_descriptor() -> None:
    deps = AgentDeps(client_id=3, locale="ua")
    code, descriptor = CoachAgent._language_context(deps)
    assert code == "uk"
    assert "Ukrainian" in descriptor

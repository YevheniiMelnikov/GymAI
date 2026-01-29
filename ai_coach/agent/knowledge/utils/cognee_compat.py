from __future__ import annotations

import importlib
import importlib.util
import pkgutil
from functools import lru_cache
from types import ModuleType
from typing import Any, Callable, Sequence


def _find_spec(module: str) -> bool:
    try:
        return importlib.util.find_spec(module) is not None
    except Exception:
        return False


def _safe_import(module: str) -> ModuleType | None:
    try:
        return importlib.import_module(module)
    except Exception:
        return None


def _walk_cognee_modules(
    cognee_pkg: ModuleType,
    *,
    must_contain: Sequence[str],
    limit: int,
) -> list[str]:
    base = getattr(cognee_pkg, "__name__", "cognee")
    paths = getattr(cognee_pkg, "__path__", None)
    if not paths:
        return []
    out: list[str] = []
    for mod in pkgutil.walk_packages(paths, prefix=f"{base}."):
        name = mod.name
        lowered = name.lower()
        ok = True
        for token in must_contain:
            if token not in lowered:
                ok = False
                break
        if not ok:
            continue
        out.append(name)
        if len(out) >= limit:
            break
    return out


def _resolve_callable(
    *,
    cognee_pkg: ModuleType,
    symbol: str,
    candidates: Sequence[str],
    walk_tokens: Sequence[str],
    walk_limit: int,
) -> tuple[Callable[..., Any] | None, str | None]:
    for module in candidates:
        if not _find_spec(module):
            continue
        imported = _safe_import(module)
        if imported is None:
            continue
        value = getattr(imported, symbol, None)
        if callable(value):
            return value, module
    for module in _walk_cognee_modules(
        cognee_pkg,
        must_contain=walk_tokens,
        limit=walk_limit,
    ):
        imported = _safe_import(module)
        if imported is None:
            continue
        value = getattr(imported, symbol, None)
        if callable(value):
            return value, module
    return None, None


@lru_cache(maxsize=1)
def resolve_get_cache_engine() -> tuple[Callable[..., Any] | None, str | None]:
    cognee_pkg = _safe_import("cognee")
    if cognee_pkg is None:
        return None, None
    candidates = (
        "cognee.infrastructure.databases.cache.get_cache_engine",
        "cognee.infrastructure.databases.cache",
        "cognee.infrastructure.cache.get_cache_engine",
        "cognee.infrastructure.cache",
        "cognee.modules.cache.get_cache_engine",
        "cognee.modules.cache",
        "cognee.modules.retrieval.cache.get_cache_engine",
        "cognee.modules.retrieval.cache",
    )
    return _resolve_callable(
        cognee_pkg=cognee_pkg,
        symbol="get_cache_engine",
        candidates=candidates,
        walk_tokens=("cache", "engine"),
        walk_limit=80,
    )


@lru_cache(maxsize=1)
def resolve_set_session_user_context_variable() -> tuple[Callable[..., Any] | None, str | None]:
    cognee_pkg = _safe_import("cognee")
    if cognee_pkg is None:
        return None, None
    candidates = (
        "cognee.modules.retrieval.utils.session_cache",
        "cognee.modules.retrieval.session_cache",
        "cognee.modules.retrieval.session_context",
        "cognee.modules.session_cache",
        "cognee.modules.session_context",
    )
    return _resolve_callable(
        cognee_pkg=cognee_pkg,
        symbol="set_session_user_context_variable",
        candidates=candidates,
        walk_tokens=("session", "cache"),
        walk_limit=120,
    )

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ai_coach.agent.knowledge.knowledge_base import KnowledgeBase

_CURRENT_KB: "KnowledgeBase | None" = None


def set_current_kb(kb: "KnowledgeBase | None") -> None:
    global _CURRENT_KB
    _CURRENT_KB = kb


def current_kb() -> "KnowledgeBase | None":
    return _CURRENT_KB


def get_current_kb() -> "KnowledgeBase":
    kb = _CURRENT_KB
    if kb is None:
        raise RuntimeError("KnowledgeBase instance not initialized")
    return kb


def get_or_create_kb() -> "KnowledgeBase":
    kb = _CURRENT_KB
    if kb is not None:
        return kb
    from ai_coach.agent.knowledge.knowledge_base import KnowledgeBase

    kb = KnowledgeBase()
    set_current_kb(kb)
    return kb

"""Compatibility module re-exporting AI coach Celery tasks."""

from __future__ import annotations

from core.tasks.ai_coach_plans import *  # noqa: F401,F403
from core.tasks.ai_coach_qa import *  # noqa: F401,F403

# Explicit re-export to satisfy tools relying on __all__ from the legacy module.
from core.tasks.ai_coach_plans import __all__ as _plans_all
from core.tasks.ai_coach_qa import __all__ as _qa_all

__all__ = tuple(set(_plans_all) | set(_qa_all))

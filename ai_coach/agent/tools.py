"""Minimal tools for CoachAgent tests."""

from __future__ import annotations

from typing import Protocol

from loguru import logger  # pyrefly: ignore[import-error]

from core.cache import Cache
from core.resources.exercises import exercise_dict
from core.schemas import DayExercises
from core.utils.short_url import short_url
from .base import AgentDeps


class ToolContext(Protocol):
    deps: AgentDeps


async def tool_search_knowledge(ctx: ToolContext, query: str, k: int = 6) -> list[str]:
    from ai_coach.agent.knowledge.knowledge_base import KnowledgeBase

    client_id = ctx.deps.client_id
    logger.debug(f"tool_search_knowledge client_id={client_id} query='{query[:80]}' k={k}")
    try:
        return await KnowledgeBase.search(query, client_id, k)
    except Exception as e:  # pragma: no cover - forward error
        logger.warning(f"knowledge search failed: {e}")
        return []


async def tool_attach_gifs(ctx: ToolContext, exercises: list[DayExercises]) -> list[DayExercises]:
    client_id = ctx.deps.client_id
    logger.debug(f"tool_attach_gifs client_id={client_id}")
    try:
        from core.services import get_gif_manager

        gif_manager = get_gif_manager()
    except Exception as e:  # pragma: no cover - optional service
        logger.warning(f"gif manager unavailable: {e}")
        return exercises

    result: list[DayExercises] = []
    for day in exercises:
        new_day = DayExercises(day=day.day, exercises=[])
        for ex in day.exercises:
            try:
                link = await gif_manager.find_gif(ex.name, exercise_dict)
            except Exception as e:
                logger.debug(f"find_gif failed name={ex.name} err={e}")
                link = None
            ex_copy = ex.model_copy()
            if link:
                try:
                    short = await short_url(link)
                except Exception as e:
                    logger.debug(f"short_url failed link={link} err={e}")
                    short = link
                ex_copy.gif_link = short
                try:
                    await Cache.workout.cache_gif_filename(ex.name, link.split("/")[-1])
                except Exception as e:  # pragma: no cover - cache errors ignored
                    logger.debug(f"cache_gif_filename failed name={ex.name} err={e}")
            new_day.exercises.append(ex_copy)
        result.append(new_day)
    return result

#!/usr/bin/env python
import argparse
import asyncio
from typing import Sequence

from ai_coach.agent.knowledge.cognee_config import CogneeConfig
from ai_coach.agent.knowledge.knowledge_base import ensure_cognee_setup
from ai_coach.agent.knowledge.utils.datasets import DatasetService
from config.app_settings import settings


async def _cleanup(aliases: Sequence[str], drop_all: bool) -> None:
    CogneeConfig.apply()
    await ensure_cognee_setup()
    service = DatasetService()
    for alias in aliases:
        normalized = service.alias_for_dataset(alias)
        if not normalized:
            print(f"[skip] empty alias provided ({alias!r})")
            continue
        pruned = await service.purge_dataset(normalized, drop_all=drop_all)
        action = "purged" if drop_all else "healed"
        if pruned:
            print(f"[ok] {action} dataset {normalized}")
        else:
            print(f"[noop] nothing to {action} for {normalized}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Cleanup Cognee datasets by alias. "
            "Use --drop-all to delete every dataset row and allow Cognee to recreate a clean entry."
        )
    )
    parser.add_argument(
        "--alias",
        action="append",
        dest="aliases",
        help="Dataset alias to clean up. Defaults to the global dataset.",
    )
    parser.add_argument(
        "--drop-all",
        action="store_true",
        help="Remove every dataset row for the alias instead of keeping the oldest one.",
    )
    args = parser.parse_args()

    aliases = args.aliases or [settings.COGNEE_GLOBAL_DATASET]
    asyncio.run(_cleanup(aliases, drop_all=args.drop_all))


if __name__ == "__main__":
    main()

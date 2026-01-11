from dataclasses import dataclass


@dataclass(frozen=True)
class ExerciseCatalogEntry:
    gif_key: str
    canonical: str
    aliases: tuple[str, ...]
    category: str
    primary_muscles: tuple[str, ...]
    secondary_muscles: tuple[str, ...]
    equipment: tuple[str, ...]

    def matches_name(self, query: str) -> bool:
        needle = query.lower()
        if needle in self.canonical.lower():
            return True
        return any(needle in alias.lower() for alias in self.aliases)


__all__ = ["ExerciseCatalogEntry"]

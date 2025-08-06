from .coach_utils import init_ai_coach, coach_ready_event

__all__ = ["init_ai_coach", "coach_ready_event", "HashStore"]


def __getattr__(name: str):
    if name == "HashStore":  # pragma: no cover - lazy import
        from .hash_store import HashStore

        return HashStore
    raise AttributeError(name)

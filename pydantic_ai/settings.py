"""Settings stub for pydantic_ai."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ModelSettings:
    """Minimal model settings used in tests."""

    model: str | None = None
    temperature: float | None = None

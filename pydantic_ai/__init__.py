"""Lightweight stubs for optional pydantic_ai dependency used in tests."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, TypeVar

T = TypeVar("T")


class ModelRetry(Exception):
    """Raised by tools to signal model retry."""


@dataclass
class RunContext(Generic[T]):
    """Holds dependencies provided to tool functions."""

    deps: T

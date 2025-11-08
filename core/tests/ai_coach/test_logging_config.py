import logging

import pytest

from ai_coach.logging_config import SamplingFilter
import ai_coach.logging_config as logging_config


def _make_record(message: str) -> logging.LogRecord:
    return logging.LogRecord(
        name="test_logger",
        level=logging.INFO,
        pathname=__file__,
        lineno=0,
        msg=message,
        args=(),
        exc_info=None,
    )


def test_sampling_filter_suppresses_duplicates(monkeypatch):
    filter_ = SamplingFilter(ttl=0.5)
    times = iter([0.0, 0.0, 1.0])
    monkeypatch.setattr(logging_config.time, "monotonic", lambda: next(times))

    first = _make_record("repeated_message")
    second = _make_record("repeated_message")
    third = _make_record("repeated_message")

    assert filter_.filter(first) is True
    assert filter_.filter(second) is False
    assert filter_.filter(third) is True
    assert "(suppressed=1)" in third.msg

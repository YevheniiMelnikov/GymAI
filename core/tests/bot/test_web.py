import pytest

from bot.utils.web import build_ping_url


def test_build_ping_url_appends_ping() -> None:
    assert build_ping_url("https://example.com/telegram/webhook") == "https://example.com/telegram/webhook/__ping"


def test_build_ping_url_strips_trailing_slash() -> None:
    assert build_ping_url("https://example.com/telegram/webhook/") == "https://example.com/telegram/webhook/__ping"


def test_build_ping_url_missing_value() -> None:
    with pytest.raises(ValueError):
        build_ping_url(None)

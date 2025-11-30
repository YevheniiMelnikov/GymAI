from types import SimpleNamespace

from core.internal_http import resolve_hmac_credentials


def test_resolve_hmac_credentials_ordering() -> None:
    cases = [
        (
            {
                "AI_COACH_INTERNAL_KEY_ID": "ak",
                "AI_COACH_INTERNAL_API_KEY": "as",
                "INTERNAL_KEY_ID": "ik",
                "INTERNAL_API_KEY": "is",
            },
            ("ak", "as"),
        ),
        (
            {
                "AI_COACH_INTERNAL_KEY_ID": "",
                "AI_COACH_INTERNAL_API_KEY": "",
                "INTERNAL_KEY_ID": "ik",
                "INTERNAL_API_KEY": "is",
            },
            ("ik", "is"),
        ),
        (
            {
                "AI_COACH_INTERNAL_KEY_ID": "",
                "AI_COACH_INTERNAL_API_KEY": "",
                "INTERNAL_KEY_ID": "",
                "INTERNAL_API_KEY": "",
            },
            None,
        ),
    ]
    for payload, expected in cases:
        settings = SimpleNamespace(**payload)
        assert resolve_hmac_credentials(settings, prefer_ai_coach=True) == expected

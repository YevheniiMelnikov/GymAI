from types import SimpleNamespace

from apps.webapp import utils


def test_transform_days_includes_gif_url(monkeypatch) -> None:
    storage = SimpleNamespace(bucket=object(), find_gif=lambda _name: "https://cdn/gif.gif")
    monkeypatch.setattr(utils, "_get_gif_storage", lambda: storage)

    exercises = [
        {"day": "Day 1", "exercises": [{"name": "Foo", "sets": "3", "reps": "10", "gif_key": "gif.gif"}]},
    ]

    result = utils.transform_days(exercises)

    assert result[0]["exercises"][0]["gif_url"] == "/api/gif/gif.gif"

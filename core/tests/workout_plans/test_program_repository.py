from types import SimpleNamespace

from apps.workout_plans.repos import ProgramRepository


class DummyProgram:
    def __init__(self, profile, exercises_by_day, id):
        self.profile = profile
        self.exercises_by_day = exercises_by_day
        self.id = id

    def save(self):
        pass


def test_create_or_update_creates_multiple_programs(monkeypatch):
    created: list[DummyProgram] = []

    class DummyManager:
        def filter(self, **kwargs):
            existing = [p for p in created if p.profile == kwargs.get("profile_id")]
            return SimpleNamespace(first=lambda: existing[0] if existing else None)

        def create(self, **kwargs):
            program = DummyProgram(kwargs["profile_id"], kwargs["exercises_by_day"], len(created) + 1)
            created.append(program)
            return program

    monkeypatch.setattr(
        "apps.workout_plans.repos.Program.objects",
        DummyManager(),
        raising=False,
    )
    monkeypatch.setattr("apps.workout_plans.repos.cache.delete_many", lambda keys: None)

    profile = SimpleNamespace(id=1)
    first = ProgramRepository.create_or_update(profile.id, {"day1": []})
    second = ProgramRepository.create_or_update(profile.id, {"day2": []})

    assert len(created) == 2
    assert first is not second
    assert created[0].exercises_by_day == {"day1": []}
    assert created[1].exercises_by_day == {"day2": []}


def test_create_or_update_updates_existing_program(monkeypatch):
    class DummyManager:
        def create(self, **kwargs):
            raise AssertionError("should not create when updating")

    monkeypatch.setattr(
        "apps.workout_plans.repos.Program.objects",
        DummyManager(),
        raising=False,
    )
    monkeypatch.setattr("apps.workout_plans.repos.cache.delete_many", lambda keys: None)

    profile = SimpleNamespace(id=1)
    existing = DummyProgram(profile.id, {"day1": []}, id=1)

    updated = ProgramRepository.create_or_update(profile.id, {"day2": []}, instance=existing)

    assert updated is existing
    assert existing.exercises_by_day == {"day2": []}

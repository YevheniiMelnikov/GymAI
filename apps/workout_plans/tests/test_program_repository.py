from types import SimpleNamespace

from apps.workout_plans.repos import ProgramRepository


class DummyProgram:
    def __init__(self, client_profile, exercises_by_day, id):
        self.client_profile = client_profile
        self.exercises_by_day = exercises_by_day
        self.id = id

    def save(self):  # pragma: no cover - no actual DB interaction
        pass


def test_create_or_update_creates_multiple_programs(monkeypatch):
    created: list[DummyProgram] = []

    class DummyManager:
        def filter(self, **kwargs):
            existing = [p for p in created if p.client_profile == kwargs.get("client_profile")]
            return SimpleNamespace(first=lambda: existing[0] if existing else None)

        def create(self, **kwargs):
            program = DummyProgram(
                kwargs["client_profile"], kwargs["exercises_by_day"], len(created) + 1
            )
            created.append(program)
            return program

    monkeypatch.setattr(
        "apps.workout_plans.repos.Program.objects",
        DummyManager(),
        raising=False,
    )
    monkeypatch.setattr(
        "apps.workout_plans.repos.cache.delete_many", lambda keys: None
    )

    client = SimpleNamespace(id=1)
    first = ProgramRepository.create_or_update(client, {"day1": []})
    second = ProgramRepository.create_or_update(client, {"day2": []})

    assert len(created) == 2
    assert first is not second
    assert created[0].exercises_by_day == {"day1": []}
    assert created[1].exercises_by_day == {"day2": []}


def test_create_or_update_updates_existing_program(monkeypatch):
    class DummyManager:
        def create(self, **kwargs):  # pragma: no cover - creation should not happen
            raise AssertionError("should not create when updating")

    monkeypatch.setattr(
        "apps.workout_plans.repos.Program.objects",
        DummyManager(),
        raising=False,
    )
    monkeypatch.setattr(
        "apps.workout_plans.repos.cache.delete_many", lambda keys: None
    )

    client = SimpleNamespace(id=1)
    existing = DummyProgram(client, {"day1": []}, id=1)

    updated = ProgramRepository.create_or_update(client, {"day2": []}, instance=existing)

    assert updated is existing
    assert existing.exercises_by_day == {"day2": []}

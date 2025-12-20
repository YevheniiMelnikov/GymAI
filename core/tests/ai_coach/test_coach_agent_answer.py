import pytest

from ai_coach.agent.base import AgentDeps
from ai_coach.agent.coach import CoachAgent, BadRequestError
from ai_coach.exceptions import AgentExecutionAborted


class _DummyKB:
    async def get_message_history(self, profile_id: int):
        return []


class _FakeAgent:
    def __init__(self) -> None:
        self.inputs: list[object] = []
        self._fail_first = True

    async def run(self, user_input, **kwargs):
        self.inputs.append(user_input)
        if self._fail_first:
            self._fail_first = False
            raise RuntimeError("vision fail")
        return {"answer": " ok ", "sources": ["kb"]}


@pytest.mark.asyncio
async def test_answer_question_with_attachments_recovers(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_agent = _FakeAgent()
    monkeypatch.setattr(CoachAgent, "_get_agent", classmethod(lambda cls: fake_agent))
    monkeypatch.setattr("ai_coach.agent.coach.get_knowledge_base", lambda: _DummyKB())

    deps = AgentDeps(profile_id=1)
    attachments = [{"mime": "image/png", "data_base64": "Zg=="}]

    response = await CoachAgent.answer_question("Hello", deps, attachments=attachments)

    assert response.answer == "ok"
    assert len(fake_agent.inputs) == 2
    assert isinstance(fake_agent.inputs[0], dict)
    assert isinstance(fake_agent.inputs[1], str)


@pytest.mark.asyncio
async def test_answer_question_without_attachments_propagates_error(monkeypatch: pytest.MonkeyPatch) -> None:
    class _AlwaysFailAgent:
        async def run(self, user_input, **kwargs):
            raise RuntimeError("boom")

    monkeypatch.setattr(CoachAgent, "_get_agent", classmethod(lambda cls: _AlwaysFailAgent()))
    monkeypatch.setattr("ai_coach.agent.coach.get_knowledge_base", lambda: _DummyKB())

    deps = AgentDeps(profile_id=2)
    with pytest.raises(RuntimeError):
        await CoachAgent.answer_question("Hi", deps, attachments=None)


@pytest.mark.asyncio
async def test_answer_question_bad_request_with_attachments_recovers(monkeypatch: pytest.MonkeyPatch) -> None:
    class _BadRequestAgent:
        def __init__(self) -> None:
            self.calls: list[object] = []

        async def run(self, user_input, **kwargs):
            self.calls.append(user_input)
            if len(self.calls) == 1:
                raise BadRequestError("bad input")
            return {"answer": " ok ", "sources": ["kb"]}

    agent = _BadRequestAgent()
    monkeypatch.setattr(CoachAgent, "_get_agent", classmethod(lambda cls: agent))
    monkeypatch.setattr("ai_coach.agent.coach.get_knowledge_base", lambda: _DummyKB())

    deps = AgentDeps(profile_id=3)
    response = await CoachAgent.answer_question(
        "Hello",
        deps,
        attachments=[{"mime": "image/png", "data_base64": "Zg=="}],
    )

    assert response.answer == "ok"
    assert len(agent.calls) == 2


@pytest.mark.asyncio
async def test_answer_question_agent_aborted_fallback_none(monkeypatch: pytest.MonkeyPatch) -> None:
    class _AbortAgent:
        async def run(self, user_input, **kwargs):
            raise AgentExecutionAborted("abort", reason="timeout")

    monkeypatch.setattr(CoachAgent, "_get_agent", classmethod(lambda cls: _AbortAgent()))
    monkeypatch.setattr("ai_coach.agent.coach.get_knowledge_base", lambda: _DummyKB())
    monkeypatch.setattr(
        "ai_coach.agent.coach.CoachAgent._fallback_answer_question",
        classmethod(lambda cls, *a, **k: None),
    )

    deps = AgentDeps(profile_id=4)
    with pytest.raises(AgentExecutionAborted):
        await CoachAgent.answer_question("Question", deps, attachments=[{"mime": "image/png", "data_base64": "Zg=="}])


@pytest.mark.asyncio
async def test_answer_question_bad_request_without_attachments(monkeypatch: pytest.MonkeyPatch) -> None:
    class _BadRequestAgentNoAttachments:
        async def run(self, user_input, **kwargs):
            raise BadRequestError("bad input")

    monkeypatch.setattr(CoachAgent, "_get_agent", classmethod(lambda cls: _BadRequestAgentNoAttachments()))
    monkeypatch.setattr("ai_coach.agent.coach.get_knowledge_base", lambda: _DummyKB())

    deps = AgentDeps(profile_id=5)
    with pytest.raises(BadRequestError):
        await CoachAgent.answer_question("Hi", deps, attachments=None)

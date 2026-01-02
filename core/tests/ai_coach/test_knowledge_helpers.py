from ai_coach.agent.knowledge.utils.helpers import (
    KnowledgeEntry,
    filter_entries_for_prompt,
    format_knowledge_entries,
)


def test_filter_entries_for_prompt_returns_all() -> None:
    entries = [
        KnowledgeEntry(entry_id="KB-1", text="First", dataset="ds"),
        KnowledgeEntry(entry_id="KB-2", text="Second", dataset="ds"),
    ]
    result = filter_entries_for_prompt("prompt", entries)
    assert result == entries


def test_format_knowledge_entries_handles_empty() -> None:
    assert format_knowledge_entries([]) == ""

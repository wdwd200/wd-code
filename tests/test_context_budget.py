import pytest

from wdcode.context.budget import ContextBudget, apply_char_budget, apply_context_budget


def test_apply_char_budget_returns_original_text_when_within_limit():
    text, truncated = apply_char_budget("short text", 20, label="section")

    assert text == "short text"
    assert truncated is False


def test_apply_char_budget_truncates_with_labeled_marker():
    text, truncated = apply_char_budget("a" * 100, 40, label="repo_map")

    assert truncated is True
    assert text.endswith("[TRUNCATED: repo_map]")
    assert len(text) <= 40


def test_context_budget_rejects_non_positive_values():
    with pytest.raises(ValueError, match="max_agents_chars"):
        ContextBudget(max_agents_chars=0)


def test_apply_context_budget_truncates_individual_sections():
    context_text, metadata = apply_context_budget(
        agents_text="agents " * 20,
        repo_map_text="repo " * 20,
        relevant_files_text="files",
        budget=ContextBudget(
            max_total_chars=1000,
            max_agents_chars=50,
            max_repo_map_chars=45,
            max_relevant_files_chars=100,
        ),
    )

    assert "[TRUNCATED: agents]" in context_text
    assert "[TRUNCATED: repo_map]" in context_text
    assert "[TRUNCATED: relevant_files]" not in context_text
    assert metadata == {
        "agents_truncated": True,
        "repo_map_truncated": True,
        "relevant_files_truncated": False,
        "total_truncated": False,
    }


def test_apply_context_budget_supports_total_truncation():
    context_text, metadata = apply_context_budget(
        agents_text="agents " * 20,
        repo_map_text="repo " * 20,
        relevant_files_text="files " * 20,
        budget=ContextBudget(
            max_total_chars=80,
            max_agents_chars=200,
            max_repo_map_chars=200,
            max_relevant_files_chars=200,
        ),
    )

    assert context_text.endswith("[TRUNCATED: project_context]")
    assert metadata["agents_truncated"] is False
    assert metadata["repo_map_truncated"] is False
    assert metadata["relevant_files_truncated"] is False
    assert metadata["total_truncated"] is True

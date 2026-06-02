import pytest

from wdcode.context.repo_map import RepoMap, RepoMapEntry
from wdcode.context.retrieval import (
    RetrievalCandidate,
    format_retrieval_candidates,
    retrieve_relevant_files,
)


def make_entry(path, *, summary="Python source file", is_source=True, is_test=False, is_doc=False):
    return RepoMapEntry(
        path=path,
        kind="python" if path.endswith(".py") else "markdown",
        size=100,
        is_source=is_source,
        is_test=is_test,
        is_doc=is_doc,
        summary=summary,
    )


def make_repo_map(entries):
    return RepoMap(root=".", entries=tuple(entries))


def test_retrieval_matches_user_input_against_path():
    repo_map = make_repo_map(
        [
            make_entry("src/wdcode/core/agent_loop.py"),
            make_entry("src/wdcode/context/provider.py"),
        ]
    )

    candidates = retrieve_relevant_files("fix agent loop", repo_map)

    assert candidates[0].path == "src/wdcode/core/agent_loop.py"
    assert "path matched: agent" in candidates[0].reason


def test_retrieval_matches_user_input_against_filename():
    repo_map = make_repo_map(
        [
            make_entry("src/wdcode/context/provider.py"),
            make_entry("src/wdcode/core/message_builder.py"),
        ]
    )

    candidates = retrieve_relevant_files("provider", repo_map)

    assert candidates[0].path == "src/wdcode/context/provider.py"
    assert "filename matched: provider" in candidates[0].reason


def test_retrieval_prefers_test_files_for_test_related_query():
    repo_map = make_repo_map(
        [
            make_entry("src/wdcode/context/provider.py"),
            make_entry(
                "tests/test_context_provider.py",
                summary="Python test file",
                is_source=False,
                is_test=True,
            ),
        ]
    )

    candidates = retrieve_relevant_files("pytest provider", repo_map)

    assert candidates[0].path == "tests/test_context_provider.py"
    assert "test-related query" in candidates[0].reason


def test_retrieval_selects_context_directory_for_context_related_query():
    repo_map = make_repo_map(
        [
            make_entry("src/wdcode/context/retrieval.py"),
            make_entry("src/wdcode/tools/gateway.py"),
        ]
    )

    candidates = retrieve_relevant_files("context retrieval", repo_map)

    assert candidates[0].path == "src/wdcode/context/retrieval.py"
    assert "context-related query" in candidates[0].reason


def test_retrieval_returns_empty_tuple_for_empty_user_input():
    repo_map = make_repo_map([make_entry("src/wdcode/core/agent_loop.py")])

    assert retrieve_relevant_files("", repo_map) == ()


def test_retrieval_respects_max_results():
    repo_map = make_repo_map(
        [
            make_entry("src/a_module.py"),
            make_entry("src/b_module.py"),
            make_entry("src/c_module.py"),
        ]
    )

    candidates = retrieve_relevant_files("module", repo_map, max_results=2)

    assert len(candidates) == 2


def test_retrieval_rejects_non_positive_max_results():
    repo_map = make_repo_map([make_entry("src/wdcode/core/agent_loop.py")])

    with pytest.raises(ValueError, match="max_results"):
        retrieve_relevant_files("agent", repo_map, max_results=0)


def test_retrieval_sorting_is_stable_by_score_then_path():
    repo_map = make_repo_map(
        [
            make_entry("src/b_module.py"),
            make_entry("src/a_module.py"),
        ]
    )

    candidates = retrieve_relevant_files("module", repo_map)

    assert [candidate.path for candidate in candidates] == [
        "src/a_module.py",
        "src/b_module.py",
    ]


def test_format_retrieval_candidates_outputs_candidate_summary():
    output = format_retrieval_candidates(
        (
            RetrievalCandidate(
                path="src/wdcode/context/retrieval.py",
                score=10,
                reason="path matched: retrieval",
            ),
        )
    )

    assert output.startswith("# Relevant Files")
    assert "- src/wdcode/context/retrieval.py (score: 10) path matched: retrieval" in output


def test_format_retrieval_candidates_handles_empty_candidates():
    output = format_retrieval_candidates(())

    assert output == "# Relevant Files\n\nNo relevant files selected."

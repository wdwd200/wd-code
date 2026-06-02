from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory

from wdcode.context.budget import ContextBudget
from wdcode.context.provider import ContextProvider
from wdcode.core.conversation import Conversation


@contextmanager
def temp_project():
    project_root = Path(__file__).resolve().parents[1]
    temp_root = project_root / "test_tmp"
    temp_root.mkdir(exist_ok=True)
    with TemporaryDirectory(dir=temp_root) as temp_dir:
        yield Path(temp_dir)
    try:
        temp_root.rmdir()
    except OSError:
        pass


def write_file(path, content="content"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_context_provider_without_project_root_returns_empty_context():
    context = ContextProvider().build(
        user_input="context provider",
        conversation=Conversation(),
    )

    assert context.text == ""
    assert context.metadata is None


def test_context_provider_builds_agents_repo_map_and_relevant_files_context():
    with temp_project() as project:
        write_file(project / "AGENTS.md", "# Test Agents\n\nFollow local rules.")
        write_file(
            project / "src/wdcode/context/provider.py",
            "SECRET_BODY_SHOULD_NOT_APPEAR = True",
        )
        write_file(project / "src/wdcode/core/agent_loop.py", "content")
        write_file(project / "tests/test_context_provider.py", "content")

        context = ContextProvider(project_root=project).build(
            user_input="context provider tests",
            conversation=Conversation(),
        )

    assert "# Project Context" in context.text
    assert "## AGENTS.md" in context.text
    assert "# AGENTS.md" in context.text
    assert "Follow local rules." in context.text
    assert "## Repo Map" in context.text
    assert "- src/wdcode/context/provider.py [python, source] Python source file" in context.text
    assert "## Relevant Files" in context.text
    assert "src/wdcode/context/provider.py" in context.text
    assert "tests/test_context_provider.py" in context.text
    assert "SECRET_BODY_SHOULD_NOT_APPEAR" not in context.text
    assert context.metadata is not None
    assert context.metadata["budget"]["total_truncated"] is False


def test_context_provider_applies_budget_and_records_metadata():
    with temp_project() as project:
        write_file(project / "AGENTS.md", "# Test Agents\n\n" + ("Follow local rules.\n" * 20))
        write_file(
            project / "src/wdcode/context/provider.py",
            "SECRET_BODY_SHOULD_NOT_APPEAR = True",
        )
        write_file(project / "src/wdcode/context/retrieval.py", "content")
        write_file(project / "tests/test_context_provider.py", "content")

        context = ContextProvider(
            project_root=project,
            budget=ContextBudget(
                max_total_chars=500,
                max_agents_chars=80,
                max_repo_map_chars=140,
                max_relevant_files_chars=120,
            ),
        ).build(
            user_input="context provider tests",
            conversation=Conversation(),
        )

    assert "[TRUNCATED:" in context.text
    assert "SECRET_BODY_SHOULD_NOT_APPEAR" not in context.text
    assert context.metadata is not None
    assert any(context.metadata["budget"].values())

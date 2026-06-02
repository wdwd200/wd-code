from contextlib import contextmanager
from pathlib import Path
import shutil
import subprocess
from tempfile import TemporaryDirectory

import pytest

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


def require_git():
    if shutil.which("git") is None:
        pytest.skip("git is not available")


def run_git(project, *args):
    result = subprocess.run(
        ["git", *args],
        cwd=project,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=10,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return result


def init_repo(project):
    require_git()
    run_git(project, "init")
    run_git(project, "config", "user.email", "tests@example.invalid")
    run_git(project, "config", "user.name", "Tests")


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
            "\n".join(
                [
                    "import pathlib",
                    "",
                    "class ContextProvider:",
                    "    def build(self):",
                    "        return 'SECRET_BODY_SHOULD_NOT_APPEAR'",
                    "",
                    "def helper():",
                    "    return 'HELPER_BODY_SHOULD_NOT_APPEAR'",
                ]
            ),
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
    assert "## Recent Files" in context.text
    assert "## Symbol Index" in context.text
    assert "## Relevant Files" in context.text
    assert "src/wdcode/context/provider.py" in context.text
    assert "tests/test_context_provider.py" in context.text
    assert "ContextProvider(class)" in context.text
    assert "helper(function)" in context.text
    assert "pathlib" in context.text
    assert "SECRET_BODY_SHOULD_NOT_APPEAR" not in context.text
    assert "HELPER_BODY_SHOULD_NOT_APPEAR" not in context.text
    assert context.metadata is not None
    assert context.metadata["budget"]["total_truncated"] is False
    assert context.metadata["recent_files_count"] == 0
    assert context.metadata["symbol_index_files_count"] == 1


def test_context_provider_includes_recent_files_from_git_status():
    with temp_project() as project:
        init_repo(project)
        write_file(project / "AGENTS.md", "# Test Agents\n")
        write_file(project / "src/wdcode/context/provider.py", "content")
        write_file(
            project / "src/wdcode/context/recent_files.py",
            "RECENT_BODY_SHOULD_NOT_APPEAR = True",
        )

        context = ContextProvider(project_root=project).build(
            user_input="context recent files",
            conversation=Conversation(),
        )

    assert "## Recent Files" in context.text
    assert "- AGENTS.md [untracked] git status: ??" in context.text
    assert "- src/wdcode/context/recent_files.py [untracked] git status: ??" in context.text
    assert "RECENT_BODY_SHOULD_NOT_APPEAR" not in context.text
    assert context.metadata is not None
    assert context.metadata["recent_files_count"] >= 1


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
                max_recent_files_chars=80,
                max_symbol_index_chars=120,
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


def test_context_provider_can_truncate_recent_files_section():
    with temp_project() as project:
        init_repo(project)
        write_file(project / "AGENTS.md", "# Test Agents\n")
        for index in range(6):
            write_file(project / f"src/file_{index}.py", "RECENT_BODY_SHOULD_NOT_APPEAR")

        context = ContextProvider(
            project_root=project,
            budget=ContextBudget(
                max_total_chars=1000,
                max_agents_chars=200,
                max_repo_map_chars=400,
                max_recent_files_chars=70,
                max_symbol_index_chars=400,
                max_relevant_files_chars=200,
            ),
        ).build(
            user_input="recent files",
            conversation=Conversation(),
        )

    assert "[TRUNCATED: recent_files]" in context.text
    assert "RECENT_BODY_SHOULD_NOT_APPEAR" not in context.text
    assert context.metadata is not None
    assert context.metadata["budget"]["recent_files_truncated"] is True


def test_context_provider_can_truncate_symbol_index_section():
    with temp_project() as project:
        write_file(project / "AGENTS.md", "# Test Agents\n")
        for index in range(6):
            write_file(
                project / f"src/module_{index}.py",
                f"def symbol_{index}():\n    return 'SYMBOL_BODY_SHOULD_NOT_APPEAR'\n",
            )

        context = ContextProvider(
            project_root=project,
            budget=ContextBudget(
                max_total_chars=1200,
                max_agents_chars=200,
                max_repo_map_chars=400,
                max_recent_files_chars=200,
                max_symbol_index_chars=80,
                max_relevant_files_chars=200,
            ),
        ).build(
            user_input="symbol index",
            conversation=Conversation(),
        )

    assert "## Symbol Index" in context.text
    assert "[TRUNCATED: symbol_index]" in context.text
    assert "SYMBOL_BODY_SHOULD_NOT_APPEAR" not in context.text
    assert context.metadata is not None
    assert context.metadata["symbol_index_files_count"] == 6
    assert context.metadata["budget"]["symbol_index_truncated"] is True

from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from wdcode.context import AgentsContext, format_agents_context, load_agents_context


@pytest.fixture
def tmp_path():
    project_root = Path(__file__).resolve().parents[1]
    temp_root = project_root / "test_tmp"
    temp_root.mkdir(exist_ok=True)
    with TemporaryDirectory(dir=temp_root) as temp_dir:
        yield Path(temp_dir)
    try:
        temp_root.rmdir()
    except OSError:
        pass


def test_load_agents_context_returns_none_when_missing(tmp_path):
    context = load_agents_context(tmp_path)

    assert context is None
    assert "No AGENTS.md found" in format_agents_context(None)


def test_load_agents_context_reads_root_agents_file(tmp_path):
    agents_file = tmp_path / "AGENTS.md"
    agents_file.write_text("# Test Agents\n\nFollow the project rules.\n", encoding="utf-8")

    context = load_agents_context(tmp_path)
    output = format_agents_context(context)

    assert isinstance(context, AgentsContext)
    assert context.path == "AGENTS.md"
    assert "Follow the project rules." in context.content
    assert context.truncated is False
    assert "Path: AGENTS.md" in output
    assert "Truncated: false" in output
    assert "```markdown" in output


def test_load_agents_context_truncates_long_content(tmp_path):
    (tmp_path / "AGENTS.md").write_text("0123456789" * 5, encoding="utf-8")

    context = load_agents_context(tmp_path, max_chars=20)
    output = format_agents_context(context)

    assert context is not None
    assert context.truncated is True
    assert "[TRUNCATED]" in context.content
    assert "Truncated: true" in output


def test_load_agents_context_rejects_missing_project_root(tmp_path):
    with pytest.raises(ValueError, match="does not exist"):
        load_agents_context(tmp_path / "missing")


def test_load_agents_context_rejects_file_project_root(tmp_path):
    file_path = tmp_path / "file.txt"
    file_path.write_text("content", encoding="utf-8")

    with pytest.raises(ValueError, match="not a directory"):
        load_agents_context(file_path)


def test_load_agents_context_rejects_non_positive_max_chars(tmp_path):
    with pytest.raises(ValueError, match="max_chars"):
        load_agents_context(tmp_path, max_chars=0)


def test_load_agents_context_only_reads_root_agents_file(tmp_path):
    subdir = tmp_path / "subdir"
    subdir.mkdir()
    (subdir / "AGENTS.md").write_text("# Nested Agents\n", encoding="utf-8")

    assert load_agents_context(tmp_path) is None


def test_load_agents_context_ignores_directory_named_agents(tmp_path):
    (tmp_path / "AGENTS.md").mkdir()

    assert load_agents_context(tmp_path) is None

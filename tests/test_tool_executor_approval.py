from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory

from wdcode.tools import create_default_registry
from wdcode.tools.executor import ToolExecutor


@contextmanager
def project_temp_dir():
    project_root = Path(__file__).resolve().parents[1]
    temp_root = project_root / "test_tmp"
    temp_root.mkdir(exist_ok=True)
    with TemporaryDirectory(dir=temp_root) as temp_dir:
        yield project_root, Path(temp_dir)
    try:
        temp_root.rmdir()
    except OSError:
        pass


class RecordingRegistry:
    def __init__(self):
        self.calls = []

    def execute(self, name, arguments):
        self.calls.append((name, arguments))
        return {"executed": True}


def test_tool_executor_dry_run_allows_read_tools():
    project_root = Path(__file__).resolve().parents[1]
    executor = ToolExecutor(create_default_registry(project_root), approval_mode="dry_run")

    result = executor.execute("list_files", {"path": "tests"})

    assert result.ok is True
    assert "entries" in result.data


def test_tool_executor_dry_run_write_file_does_not_create_file():
    with project_temp_dir() as (project_root, temp_dir):
        target = temp_dir / "created.txt"
        relative_target = target.relative_to(project_root).as_posix()
        executor = ToolExecutor(create_default_registry(project_root), approval_mode="dry_run")

        result = executor.execute(
            "write_file",
            {
                "path": relative_target,
                "content": "should not be written",
            },
        )

        assert result.ok is False
        assert result.metadata["approval_mode"] == "dry_run"
        assert result.metadata["dry_run"] is True
        assert result.metadata["tool_name"] == "write_file"
        assert not target.exists()


def test_tool_executor_dry_run_edit_file_does_not_modify_file():
    with project_temp_dir() as (project_root, temp_dir):
        target = temp_dir / "existing.txt"
        target.write_text("original", encoding="utf-8")
        relative_target = target.relative_to(project_root).as_posix()
        executor = ToolExecutor(create_default_registry(project_root), approval_mode="dry_run")

        result = executor.execute(
            "edit_file",
            {
                "path": relative_target,
                "old_text": "original",
                "new_text": "changed",
            },
        )

        assert result.ok is False
        assert result.metadata["approval_mode"] == "dry_run"
        assert result.metadata["dry_run"] is True
        assert result.metadata["tool_name"] == "edit_file"
        assert target.read_text(encoding="utf-8") == "original"


def test_tool_executor_dry_run_run_command_does_not_call_registry():
    registry = RecordingRegistry()
    executor = ToolExecutor(registry, approval_mode="dry_run")

    result = executor.execute("run_command", {"command": "python -m compileall tests"})

    assert result.ok is False
    assert result.metadata["approval_mode"] == "dry_run"
    assert result.metadata["dry_run"] is True
    assert result.metadata["tool_name"] == "run_command"
    assert registry.calls == []


def test_tool_executor_require_approval_does_not_call_registry_for_mutating_tool():
    registry = RecordingRegistry()
    executor = ToolExecutor(registry, approval_mode="require_approval")

    result = executor.execute("write_file", {"path": "example.txt", "content": "data"})

    assert result.ok is False
    assert result.metadata["approval_mode"] == "require_approval"
    assert result.metadata["dry_run"] is False
    assert result.metadata["tool_name"] == "write_file"
    assert registry.calls == []

import shutil
import subprocess
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from wdcode.context.recent_files import RecentFile, collect_recent_files, format_recent_files


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


def write_file(path, content="content"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def init_repo(project):
    require_git()
    run_git(project, "init")
    run_git(project, "config", "user.email", "tests@example.invalid")
    run_git(project, "config", "user.name", "Tests")


def commit_file(project, path, content="content"):
    write_file(project / path, content)
    run_git(project, "add", path)
    run_git(project, "commit", "-m", f"add {path}")


def test_collect_recent_files_returns_empty_for_non_git_directory():
    with temp_project() as project:
        assert collect_recent_files(project) == ()


def test_collect_recent_files_detects_modified_file():
    with temp_project() as project:
        init_repo(project)
        commit_file(project, "src/a.py")
        write_file(project / "src/a.py", "modified")

        files = collect_recent_files(project)

    assert files == (
        RecentFile(path="src/a.py", status="modified", reason="git status: M"),
    )


def test_collect_recent_files_detects_untracked_file():
    with temp_project() as project:
        init_repo(project)
        write_file(project / "src/new.py")

        files = collect_recent_files(project)

    assert files == (
        RecentFile(path="src/new.py", status="untracked", reason="git status: ??"),
    )


def test_collect_recent_files_detects_deleted_file():
    with temp_project() as project:
        init_repo(project)
        commit_file(project, "src/delete_me.py")
        (project / "src/delete_me.py").unlink()

        files = collect_recent_files(project)

    assert files == (
        RecentFile(path="src/delete_me.py", status="deleted", reason="git status: D"),
    )


def test_collect_recent_files_detects_renamed_file_new_path():
    with temp_project() as project:
        init_repo(project)
        commit_file(project, "src/old_name.py")
        run_git(project, "mv", "src/old_name.py", "src/new_name.py")

        files = collect_recent_files(project)

    assert files == (
        RecentFile(path="src/new_name.py", status="renamed", reason="git status: R"),
    )


def test_collect_recent_files_respects_max_results():
    with temp_project() as project:
        init_repo(project)
        write_file(project / "src/c.py")
        write_file(project / "src/a.py")
        write_file(project / "src/b.py")

        files = collect_recent_files(project, max_results=2)

    assert [file.path for file in files] == ["src/a.py", "src/b.py"]


def test_collect_recent_files_rejects_non_positive_max_results():
    with temp_project() as project:
        with pytest.raises(ValueError, match="max_results"):
            collect_recent_files(project, max_results=0)


def test_format_recent_files_outputs_empty_message():
    assert format_recent_files(()) == "# Recent Files\n\nNo recent files detected."


def test_format_recent_files_uses_relative_paths_without_project_root():
    with temp_project() as project:
        init_repo(project)
        write_file(project / "src/new.py")

        output = format_recent_files(collect_recent_files(project))

    assert "- src/new.py [untracked] git status: ??" in output
    assert str(project) not in output

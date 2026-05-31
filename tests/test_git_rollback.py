import shutil
import subprocess
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from wdcode.security.rollback import GitDiffSnapshot, GitRollbackError, capture_git_diff, rollback_git_diff


pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")


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


def run_git(repo, *args, input_text=None):
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        input=input_text,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        shell=False,
    )
    assert result.returncode == 0, result.stderr
    return result


def init_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    run_git(repo, "init")
    run_git(repo, "config", "user.email", "test@example.invalid")
    run_git(repo, "config", "user.name", "Test User")
    tracked = repo / "tracked.txt"
    tracked.write_text("original\n", encoding="utf-8")
    run_git(repo, "add", ".")
    run_git(repo, "commit", "-m", "init")
    return repo


def test_capture_git_diff_clean_repo_has_no_changes(tmp_path):
    repo = init_repo(tmp_path)

    snapshot = capture_git_diff(repo)

    assert snapshot.has_changes is False
    assert snapshot.diff == ""
    assert snapshot.untracked_files == ()


def test_capture_git_diff_detects_tracked_file_change(tmp_path):
    repo = init_repo(tmp_path)
    (repo / "tracked.txt").write_text("changed\n", encoding="utf-8")

    snapshot = capture_git_diff(repo)

    assert snapshot.has_changes is True
    assert "tracked.txt" in snapshot.diff
    assert snapshot.untracked_files == ()


def test_rollback_git_diff_restores_tracked_file(tmp_path):
    repo = init_repo(tmp_path)
    tracked = repo / "tracked.txt"
    tracked.write_text("changed\n", encoding="utf-8")
    snapshot = capture_git_diff(repo)

    result = rollback_git_diff(snapshot)

    assert result == {
        "ok": True,
        "restored_tracked": True,
        "removed_untracked": [],
        "error": None,
    }
    assert tracked.read_text(encoding="utf-8") == "original\n"
    assert capture_git_diff(repo).has_changes is False


def test_capture_git_diff_records_untracked_files(tmp_path):
    repo = init_repo(tmp_path)
    (repo / "new_file.txt").write_text("new\n", encoding="utf-8")

    snapshot = capture_git_diff(repo)

    assert snapshot.has_changes is True
    assert snapshot.untracked_files == ("new_file.txt",)


def test_rollback_git_diff_removes_snapshot_untracked_file(tmp_path):
    repo = init_repo(tmp_path)
    untracked = repo / "new_file.txt"
    untracked.write_text("new\n", encoding="utf-8")
    snapshot = capture_git_diff(repo)

    result = rollback_git_diff(snapshot)

    assert result == {
        "ok": True,
        "restored_tracked": False,
        "removed_untracked": ["new_file.txt"],
        "error": None,
    }
    assert not untracked.exists()
    assert capture_git_diff(repo).has_changes is False


def test_rollback_git_diff_rejects_untracked_path_outside_project(tmp_path):
    repo = init_repo(tmp_path)
    snapshot = GitDiffSnapshot(project_root=repo, diff="", untracked_files=("../outside.txt",))

    result = rollback_git_diff(snapshot)

    assert result["ok"] is False
    assert result["removed_untracked"] == []
    assert "Unsafe untracked path" in result["error"]


def test_capture_git_diff_non_git_repo_raises_clear_error(tmp_path):
    not_repo = tmp_path / "not_repo"
    not_repo.mkdir()

    with pytest.raises(GitRollbackError, match="Not a git repository"):
        capture_git_diff(not_repo)


def test_rollback_module_does_not_use_destructive_git_commands():
    source = Path("src/wdcode/security/rollback.py").read_text(encoding="utf-8")

    assert "reset --hard" not in source
    assert "clean -fdx" not in source
    assert "shell=True" not in source

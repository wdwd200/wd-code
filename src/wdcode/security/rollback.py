import subprocess
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class GitDiffSnapshot:
    project_root: Path
    diff: str
    untracked_files: tuple[str, ...] = field(default_factory=tuple)

    @property
    def has_changes(self) -> bool:
        return bool(self.diff.strip() or self.untracked_files)


class GitRollbackError(RuntimeError):
    pass


def capture_git_diff(project_root: str | Path) -> GitDiffSnapshot:
    root = _resolve_project_root(project_root)
    _ensure_git_repository(root)
    diff = _run_git(root, ["diff", "--binary"]).stdout
    untracked = _run_git(root, ["ls-files", "--others", "--exclude-standard"]).stdout
    return GitDiffSnapshot(
        project_root=root,
        diff=diff,
        untracked_files=tuple(line for line in untracked.splitlines() if line.strip()),
    )


def rollback_git_diff(snapshot: GitDiffSnapshot) -> dict:
    removed_untracked = []
    restored_tracked = False

    if snapshot.diff.strip():
        check = _run_git_with_input(
            snapshot.project_root,
            ["apply", "--reverse", "--check"],
            snapshot.diff,
            check=False,
        )
        if check.returncode != 0:
            return _rollback_result(
                ok=False,
                restored_tracked=False,
                removed_untracked=removed_untracked,
                error=f"git apply --reverse --check failed: {check.stderr.strip()}",
            )

        apply = _run_git_with_input(
            snapshot.project_root,
            ["apply", "--reverse"],
            snapshot.diff,
            check=False,
        )
        if apply.returncode != 0:
            return _rollback_result(
                ok=False,
                restored_tracked=False,
                removed_untracked=removed_untracked,
                error=f"git apply --reverse failed: {apply.stderr.strip()}",
            )
        restored_tracked = True

    for relative_path in snapshot.untracked_files:
        try:
            target = _resolve_snapshot_path(snapshot.project_root, relative_path)
        except GitRollbackError as exc:
            return _rollback_result(False, restored_tracked, removed_untracked, str(exc))

        if target.exists():
            if not target.is_file() or target.is_symlink():
                return _rollback_result(
                    False,
                    restored_tracked,
                    removed_untracked,
                    f"Refusing to remove non-regular untracked path: {relative_path}",
                )
            target.unlink()
            removed_untracked.append(relative_path)

    return _rollback_result(True, restored_tracked, removed_untracked, None)


def _rollback_result(ok, restored_tracked, removed_untracked, error):
    return {
        "ok": ok,
        "restored_tracked": restored_tracked,
        "removed_untracked": list(removed_untracked),
        "error": error,
    }


def _resolve_project_root(project_root):
    root = Path(project_root).resolve()
    if not root.exists():
        raise GitRollbackError(f"Project root does not exist: {project_root}")
    if not root.is_dir():
        raise GitRollbackError(f"Project root is not a directory: {project_root}")
    return root


def _ensure_git_repository(project_root):
    result = _run_git(project_root, ["rev-parse", "--is-inside-work-tree"], check=False)
    if result.returncode != 0 or result.stdout.strip() != "true":
        raise GitRollbackError(f"Not a git repository: {project_root}")
    top_level = _run_git(project_root, ["rev-parse", "--show-toplevel"], check=False)
    if top_level.returncode != 0 or Path(top_level.stdout.strip()).resolve() != project_root:
        raise GitRollbackError(f"Not a git repository root: {project_root}")


def _resolve_snapshot_path(project_root, relative_path):
    raw_path = Path(relative_path)
    if raw_path.is_absolute() or any(part == ".." for part in raw_path.parts):
        raise GitRollbackError(f"Unsafe untracked path in snapshot: {relative_path}")

    target = (project_root / raw_path).resolve()
    if target != project_root and project_root not in target.parents:
        raise GitRollbackError(f"Untracked path escapes project root: {relative_path}")
    return target


def _run_git(project_root, args, check=True):
    result = subprocess.run(
        ["git", *args],
        cwd=project_root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        shell=False,
    )
    if check and result.returncode != 0:
        raise GitRollbackError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result


def _run_git_with_input(project_root, args, input_text, check=True):
    result = subprocess.run(
        ["git", *args],
        cwd=project_root,
        input=input_text,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        shell=False,
    )
    if check and result.returncode != 0:
        raise GitRollbackError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result

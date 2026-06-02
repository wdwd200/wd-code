import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class RecentFile:
    path: str
    status: str
    reason: str


def collect_recent_files(
    project_root,
    *,
    max_results: int = 12,
) -> tuple[RecentFile, ...]:
    if max_results <= 0:
        raise ValueError("max_results must be greater than zero.")

    root = Path(project_root).resolve()
    if not root.exists():
        raise ValueError(f"Project root does not exist: {project_root}")
    if not root.is_dir():
        raise ValueError(f"Project root is not a directory: {project_root}")
    if not _is_git_repository_root(root):
        return ()

    status_result = _run_git(root, ["status", "--short", "--untracked-files=all"])
    if status_result is None or status_result.returncode != 0:
        return ()

    files_by_path = {}
    for line in status_result.stdout.splitlines():
        recent_file = _parse_status_line(line)
        if recent_file is not None:
            files_by_path.setdefault(recent_file.path, recent_file)

    diff_result = _run_git(root, ["diff", "--name-only"])
    if diff_result is not None and diff_result.returncode == 0:
        for path in diff_result.stdout.splitlines():
            normalized_path = _normalize_path(path.strip())
            if normalized_path:
                files_by_path.setdefault(
                    normalized_path,
                    RecentFile(
                        path=normalized_path,
                        status="modified",
                        reason="git diff",
                    ),
                )

    return tuple(
        files_by_path[path]
        for path in sorted(files_by_path)[:max_results]
    )


def format_recent_files(files: tuple[RecentFile, ...]) -> str:
    lines = ["# Recent Files", ""]
    if not files:
        lines.append("No recent files detected.")
        return "\n".join(lines)

    for recent_file in files:
        lines.append(f"- {recent_file.path} [{recent_file.status}] {recent_file.reason}")
    return "\n".join(lines)


def _run_git(project_root: Path, args: list[str]):
    try:
        return subprocess.run(
            ["git", *args],
            cwd=project_root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=3,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None


def _is_git_repository_root(project_root: Path) -> bool:
    result = _run_git(project_root, ["rev-parse", "--show-toplevel"])
    if result is None or result.returncode != 0:
        return False
    return Path(result.stdout.strip()).resolve() == project_root


def _parse_status_line(line: str) -> RecentFile | None:
    if len(line) < 4:
        return None

    status_code = line[:2]
    path = line[3:].strip()
    if " -> " in path:
        path = path.split(" -> ", 1)[1]

    normalized_path = _normalize_path(path)
    if not normalized_path:
        return None

    return RecentFile(
        path=normalized_path,
        status=_status_from_code(status_code),
        reason=f"git status: {status_code.strip()}",
    )


def _status_from_code(status_code: str) -> str:
    if "?" in status_code:
        return "untracked"
    if "D" in status_code:
        return "deleted"
    if "R" in status_code:
        return "renamed"
    if status_code[0] != " ":
        return "staged"
    return "modified"


def _normalize_path(path: str) -> str:
    return path.strip('"').replace("\\", "/")

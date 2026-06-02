import os
from dataclasses import dataclass
from pathlib import Path, PurePosixPath


IGNORED_DIR_NAMES = {
    ".git",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".venv",
    "venv",
    "env",
    "node_modules",
    "dist",
    "build",
    ".eggs",
}
IGNORED_DIR_SUFFIXES = {".egg-info"}
IGNORED_FILE_NAMES = {".DS_Store", ".env"}
IGNORED_FILE_SUFFIXES = {".pyc", ".pyo", ".pyd"}


@dataclass(frozen=True)
class RepoMapEntry:
    path: str
    kind: str
    size: int
    is_source: bool
    is_test: bool
    is_doc: bool
    summary: str | None = None


@dataclass(frozen=True)
class RepoMap:
    root: str
    entries: tuple[RepoMapEntry, ...]


def build_repo_map(project_root: Path | str) -> RepoMap:
    root = Path(project_root).resolve()
    if not root.exists():
        raise ValueError(f"Project root does not exist: {project_root}")
    if not root.is_dir():
        raise ValueError(f"Project root is not a directory: {project_root}")

    entries = []
    for file_path in iter_repo_files(root):
        relative_path = file_path.relative_to(root).as_posix()
        kind = classify_file(file_path)
        is_source = is_source_file(relative_path, file_path)
        is_test = is_test_file(relative_path, file_path)
        is_doc = is_doc_file(relative_path, file_path)
        entries.append(
            RepoMapEntry(
                path=relative_path,
                kind=kind,
                size=file_path.stat().st_size,
                is_source=is_source,
                is_test=is_test,
                is_doc=is_doc,
                summary=summarize_file(kind, is_source, is_test, is_doc),
            )
        )

    return RepoMap(
        root=str(root),
        entries=tuple(sorted(entries, key=lambda entry: entry.path)),
    )


def format_repo_map(repo_map: RepoMap) -> str:
    lines = [
        "# Repo Map",
        "",
        f"Root: {repo_map.root}",
        "",
        "## Files",
        "",
    ]
    for entry in repo_map.entries:
        tags = [entry.kind]
        tags.extend(role_tags(entry))
        summary = f" {entry.summary}" if entry.summary else ""
        lines.append(f"- {entry.path} [{', '.join(tags)}]{summary}")
    return "\n".join(lines)


def iter_repo_files(project_root: Path):
    for current_root, dir_names, file_names in os.walk(project_root):
        dir_names[:] = [
            name
            for name in sorted(dir_names)
            if not should_ignore_dir(name)
        ]
        current_path = Path(current_root)
        for file_name in sorted(file_names):
            file_path = current_path / file_name
            if should_ignore_file(file_path):
                continue
            yield file_path


def should_ignore_dir(name: str) -> bool:
    return name in IGNORED_DIR_NAMES or any(name.endswith(suffix) for suffix in IGNORED_DIR_SUFFIXES)


def should_ignore_file(path: Path) -> bool:
    return path.name in IGNORED_FILE_NAMES or path.suffix.lower() in IGNORED_FILE_SUFFIXES


def classify_file(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".py":
        return "python"
    if suffix == ".md":
        return "markdown"
    if suffix in {".toml", ".yaml", ".yml", ".json"}:
        return "config"
    if suffix == ".txt":
        return "text"
    return "other"


def is_source_file(relative_path: str, path: Path) -> bool:
    parts = PurePosixPath(relative_path).parts
    return len(parts) > 1 and parts[0] == "src" and path.suffix.lower() == ".py"


def is_test_file(relative_path: str, path: Path) -> bool:
    parts = PurePosixPath(relative_path).parts
    name = path.name
    return (parts and parts[0] == "tests") or name.startswith("test_") or name.endswith("_test.py")


def is_doc_file(relative_path: str, path: Path) -> bool:
    parts = PurePosixPath(relative_path).parts
    return path.suffix.lower() == ".md" or (parts and parts[0] == "docs")


def summarize_file(kind: str, is_source: bool, is_test: bool, is_doc: bool) -> str:
    if kind == "python" and is_test:
        return "Python test file"
    if kind == "python" and is_source:
        return "Python source file"
    if is_doc:
        return "Markdown document"
    if kind == "config":
        return "Configuration file"
    if kind == "text":
        return "Text file"
    return "Other file"


def role_tags(entry: RepoMapEntry) -> list[str]:
    tags = []
    if entry.is_source:
        tags.append("source")
    if entry.is_test:
        tags.append("test")
    if entry.is_doc:
        tags.append("doc")
    return tags

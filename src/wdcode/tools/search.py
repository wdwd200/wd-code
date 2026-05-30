from pathlib import Path

from wdcode.security.paths import MAX_FILE_BYTES, check_allowed_text_file, check_file_size, resolve_project_path
from wdcode.tools.base import Tool


MAX_SEARCH_FILES = 200
MAX_SEARCH_BYTES = 1_000_000
MAX_SEARCH_MATCHES = 50


def create_search_tools(project_root):
    root = Path(project_root).resolve()
    return [
        Tool(
            name="search_files",
            description="Search allowed project text files by file name or file content.",
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Text to search for in file names and file contents.",
                    },
                    "path": {
                        "type": "string",
                        "description": "Project-relative directory or file path to search. Defaults to project root.",
                    },
                },
                "required": ["query"],
                "additionalProperties": False,
            },
            execute=lambda arguments: search_files(root, arguments),
        )
    ]


def search_files(project_root, arguments):
    query = arguments.get("query")
    path = resolve_project_path(project_root, arguments.get("path", "."))
    if not path.exists():
        raise FileNotFoundError(f"Path not found: {arguments.get('path', '.')}")

    matches = []
    scanned_files = 0
    scanned_bytes = 0
    for file_path in iter_search_files(project_root, path):
        if scanned_files >= MAX_SEARCH_FILES or scanned_bytes >= MAX_SEARCH_BYTES:
            break
        size = file_path.stat().st_size
        scanned_files += 1
        scanned_bytes += size

        relative_path = str(file_path.relative_to(project_root))
        if query.lower() in file_path.name.lower():
            matches.append({"path": relative_path, "match": "file_name"})
            continue

        try:
            content = file_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue

        for line_number, line in enumerate(content.splitlines(), start=1):
            if query.lower() in line.lower():
                matches.append(
                    {
                        "path": relative_path,
                        "match": "content",
                        "line": line_number,
                        "preview": line.strip(),
                    }
                )
                break

        if len(matches) >= MAX_SEARCH_MATCHES:
            break

    return {
        "matches": matches,
        "scanned_files": scanned_files,
        "scanned_bytes": scanned_bytes,
    }


def iter_search_files(project_root, path):
    candidates = [path] if path.is_file() else path.rglob("*")
    for candidate in candidates:
        if not candidate.is_file():
            continue
        try:
            check_allowed_text_file(candidate, project_root, allow_read=True)
            check_file_size(candidate, MAX_FILE_BYTES)
        except ValueError:
            continue
        yield candidate

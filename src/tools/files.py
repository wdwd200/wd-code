from pathlib import Path

from tools.tool import Tool

TEXT_FILE_EXTENSIONS = {
    ".bat",
    ".cmd",
    ".css",
    ".html",
    ".ini",
    ".js",
    ".json",
    ".md",
    ".py",
    ".txt",
    ".yaml",
    ".yml",
}


def create_file_tools(project_root):
    root = Path(project_root).resolve()
    return [
        Tool(
            name="list_files",
            description="List files and directories under a project-relative directory.",
            parameters={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Project-relative directory path. Use . for the project root.",
                    }
                },
                "required": ["path"],
                "additionalProperties": False,
            },
            execute=lambda arguments: list_files(root, arguments),
        ),
        Tool(
            name="read_file",
            description="Read a project-relative text file.",
            parameters={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Project-relative text file path.",
                    }
                },
                "required": ["path"],
                "additionalProperties": False,
            },
            execute=lambda arguments: read_file(root, arguments),
        ),
    ]


def resolve_project_path(project_root, user_path):
    if not user_path:
        raise ValueError("Missing path.")

    candidate = (project_root / user_path).resolve()
    if candidate != project_root and project_root not in candidate.parents:
        raise ValueError("Path is outside the project root.")
    return candidate


def list_files(project_root, arguments):
    path = resolve_project_path(project_root, arguments.get("path"))
    if not path.exists():
        raise FileNotFoundError(f"Directory not found: {arguments.get('path')}")
    if not path.is_dir():
        raise NotADirectoryError(f"Not a directory: {arguments.get('path')}")

    entries = []
    for child in sorted(path.iterdir(), key=lambda item: item.name.lower()):
        entries.append(
            {
                "name": child.name,
                "path": str(child.relative_to(project_root)),
                "type": "directory" if child.is_dir() else "file",
            }
        )
    return {"entries": entries}


def read_file(project_root, arguments):
    path = resolve_project_path(project_root, arguments.get("path"))
    if not path.exists():
        raise FileNotFoundError(f"File not found: {arguments.get('path')}")
    if not path.is_file():
        raise IsADirectoryError(f"Not a file: {arguments.get('path')}")
    if path.suffix.lower() not in TEXT_FILE_EXTENSIONS:
        raise ValueError(f"Not an allowed text file type: {path.suffix}")

    return {
        "path": str(path.relative_to(project_root)),
        "content": path.read_text(encoding="utf-8"),
    }

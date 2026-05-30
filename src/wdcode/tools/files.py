from pathlib import Path

from wdcode.security.paths import (
    MAX_FILE_BYTES,
    check_allowed_text_file,
    check_file_size,
    check_sensitive_path,
    resolve_project_path,
)
from wdcode.tools.base import Tool


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
        Tool(
            name="write_file",
            description="Write a project-relative text file. Requires overwrite=true for existing files.",
            parameters={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Project-relative text file path.",
                    },
                    "content": {
                        "type": "string",
                        "description": "File content to write.",
                    },
                    "overwrite": {
                        "type": "boolean",
                        "description": "Whether to replace an existing file.",
                    },
                },
                "required": ["path", "content"],
                "additionalProperties": False,
            },
            execute=lambda arguments: write_file(root, arguments),
        ),
        Tool(
            name="edit_file",
            description="Edit a project-relative text file by replacing exact text.",
            parameters={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Project-relative text file path.",
                    },
                    "old_text": {
                        "type": "string",
                        "description": "Exact text to replace.",
                    },
                    "new_text": {
                        "type": "string",
                        "description": "Replacement text.",
                    },
                },
                "required": ["path", "old_text", "new_text"],
                "additionalProperties": False,
            },
            execute=lambda arguments: edit_file(root, arguments),
        ),
    ]


def list_files(project_root, arguments):
    path = resolve_project_path(project_root, arguments.get("path"))
    if not path.exists():
        raise FileNotFoundError(f"Directory not found: {arguments.get('path')}")
    if not path.is_dir():
        raise NotADirectoryError(f"Not a directory: {arguments.get('path')}")

    entries = []
    for child in sorted(path.iterdir(), key=lambda item: item.name.lower()):
        try:
            check_sensitive_path(child, project_root, allow_read=True)
            if child.is_symlink():
                continue
        except ValueError:
            continue
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
    check_allowed_text_file(path, project_root, allow_read=True)
    check_file_size(path, MAX_FILE_BYTES)

    return {
        "path": str(path.relative_to(project_root)),
        "content": path.read_text(encoding="utf-8"),
    }


def write_file(project_root, arguments):
    path = resolve_project_path(project_root, arguments.get("path"))
    check_allowed_text_file(path, project_root, allow_read=False)
    if path.exists() and path.is_symlink():
        raise ValueError("Cannot write symbolic link paths.")
    path.parent.mkdir(parents=True, exist_ok=True)
    path = resolve_project_path(project_root, arguments.get("path"))
    check_allowed_text_file(path, project_root, allow_read=False)
    if path.exists() and path.is_symlink():
        raise ValueError("Cannot write symbolic link paths.")
    path.write_text(arguments.get("content"), encoding="utf-8")
    return {
        "path": str(path.relative_to(project_root)),
        "bytes_written": len(arguments.get("content").encode("utf-8")),
    }


def edit_file(project_root, arguments):
    path = resolve_project_path(project_root, arguments.get("path"))
    check_allowed_text_file(path, project_root, allow_read=False)
    if path.is_symlink():
        raise ValueError("Cannot edit symbolic link paths.")
    check_file_size(path, MAX_FILE_BYTES)
    content = path.read_text(encoding="utf-8")
    old_text = arguments.get("old_text")
    new_text = arguments.get("new_text")

    count = content.count(old_text)
    if count == 0:
        raise ValueError("old_text was not found.")
    if count > 1:
        raise ValueError("old_text matched more than once.")

    updated = content.replace(old_text, new_text, 1)
    path.write_text(updated, encoding="utf-8")
    return {
        "path": str(path.relative_to(project_root)),
        "replacements": 1,
    }

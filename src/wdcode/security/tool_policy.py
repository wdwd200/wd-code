from dataclasses import dataclass
from pathlib import Path

from wdcode.security.paths import (
    MAX_FILE_BYTES,
    MAX_WRITE_BYTES,
    check_allowed_text_file,
    check_file_size,
    check_sensitive_path,
    resolve_project_path,
)


ALLOWED_TOOL_NAMES = {"list_files", "read_file", "search_files", "write_file", "edit_file", "run_command"}
READ_TOOLS = {"list_files", "read_file", "search_files"}


@dataclass(frozen=True)
class ToolPermission:
    allowed: bool
    reason: str
    normalized_arguments: dict


def check_tool_permission(tool_name, arguments, project_root):
    if tool_name not in ALLOWED_TOOL_NAMES:
        return deny(f"Tool is not allowed: {tool_name}", arguments)
    if not isinstance(arguments, dict):
        return deny("Tool arguments must be an object.", {})

    root = Path(project_root).resolve()
    try:
        normalized = normalize_arguments(tool_name, arguments, root)
    except ValueError as exc:
        return deny(str(exc), arguments)

    return ToolPermission(True, "Allowed.", normalized)


def deny(reason, arguments):
    return ToolPermission(False, reason, dict(arguments) if isinstance(arguments, dict) else {})


def normalize_arguments(tool_name, arguments, project_root):
    normalized = dict(arguments)

    if tool_name in {"list_files", "read_file", "write_file", "edit_file"}:
        path = require_string(arguments, "path")
        resolved = resolve_project_path(project_root, path)
        check_sensitive_path(resolved, project_root, allow_read=tool_name in READ_TOOLS)
        normalized["path"] = str(resolved.relative_to(project_root))

        if tool_name in {"read_file", "write_file", "edit_file"}:
            check_allowed_text_file(resolved, project_root, allow_read=tool_name == "read_file")
        if tool_name == "read_file" and resolved.exists():
            check_file_size(resolved, MAX_FILE_BYTES)

    if tool_name == "search_files":
        query = require_string(arguments, "query")
        if not query.strip():
            raise ValueError("Search query cannot be empty.")
        path = arguments.get("path", ".")
        if not isinstance(path, str):
            raise ValueError("path must be a string.")
        resolved = resolve_project_path(project_root, path)
        if resolved.is_file():
            check_allowed_text_file(resolved, project_root, allow_read=True)
            check_file_size(resolved, MAX_FILE_BYTES)
        else:
            check_sensitive_path(resolved, project_root, allow_read=True)
        normalized["query"] = query
        normalized["path"] = str(resolved.relative_to(project_root)) if resolved != project_root else "."

    if tool_name == "write_file":
        content = require_string(arguments, "content")
        if len(content.encode("utf-8")) > MAX_WRITE_BYTES:
            raise ValueError("Content is too large to write.")
        overwrite = arguments.get("overwrite", False)
        if not isinstance(overwrite, bool):
            raise ValueError("overwrite must be a boolean.")
        target = project_root / normalized["path"]
        if target.exists() and not overwrite:
            raise ValueError("File exists. Set overwrite=true to replace it.")
        normalized["content"] = content
        normalized["overwrite"] = overwrite

    if tool_name == "edit_file":
        old_text = require_string(arguments, "old_text")
        new_text = require_string(arguments, "new_text")
        if not old_text:
            raise ValueError("old_text cannot be empty.")
        if len(new_text.encode("utf-8")) > MAX_WRITE_BYTES:
            raise ValueError("new_text is too large.")
        target = project_root / normalized["path"]
        if not target.exists():
            raise ValueError("File to edit does not exist.")
        check_file_size(target, MAX_FILE_BYTES)
        normalized["old_text"] = old_text
        normalized["new_text"] = new_text

    if tool_name == "run_command":
        command = require_string(arguments, "command")
        cwd = arguments.get("cwd", ".")
        if not isinstance(cwd, str):
            raise ValueError("cwd must be a string.")
        resolved = resolve_project_path(project_root, cwd)
        if not resolved.exists():
            raise ValueError("cwd does not exist.")
        if not resolved.is_dir():
            raise ValueError("cwd must be a directory.")
        timeout = arguments.get("timeout", 30)
        if not isinstance(timeout, (int, float)) or isinstance(timeout, bool):
            raise ValueError("timeout must be a number.")
        if timeout <= 0:
            raise ValueError("timeout must be greater than zero.")
        normalized["command"] = command
        normalized["cwd"] = str(resolved.relative_to(project_root)) if resolved != project_root else "."
        normalized["timeout"] = min(float(timeout), 120.0)

    return normalized


def require_string(arguments, name):
    value = arguments.get(name)
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a string.")
    return value

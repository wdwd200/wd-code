from pathlib import Path


SENSITIVE_DIR_NAMES = {".git", ".idea", "__pycache__", ".venv", "venv", "env", "secrets", "credentials"}
SENSITIVE_FILE_NAMES = {"model_config.json", ".env"}
SENSITIVE_NAME_WORDS = {"secret", "secrets", "credential", "credentials", "token", "key", "apikey", "api", "env"}
SENSITIVE_STEMS = {"api_key", "api-token", "access_token", "access-token", "private_key", "private-key"}
TEXT_FILE_EXTENSIONS = {".md", ".py", ".txt"}
MAX_FILE_BYTES = 200_000
MAX_WRITE_BYTES = 100_000


def resolve_project_path(project_root, user_path):
    if not user_path:
        raise ValueError("Missing path.")
    raw_path = Path(user_path)
    if raw_path.is_absolute():
        raise ValueError("Absolute paths are not allowed.")
    if any(part == ".." for part in raw_path.parts):
        raise ValueError("Path traversal is not allowed.")

    candidate = (project_root / raw_path).resolve()
    if candidate != project_root and project_root not in candidate.parents:
        raise ValueError("Path is outside the project root.")
    return candidate


def check_sensitive_path(path, project_root, allow_read):
    relative_parts = path.relative_to(project_root).parts if path != project_root else ()
    lowered_parts = [part.lower() for part in relative_parts]
    lowered_name = path.name.lower()

    if any(part in SENSITIVE_DIR_NAMES for part in lowered_parts):
        raise ValueError("Access to sensitive directories is not allowed.")
    if lowered_name in SENSITIVE_FILE_NAMES:
        raise ValueError("Access to sensitive config files is not allowed.")
    if has_sensitive_name(lowered_parts):
        raise ValueError("Access to sensitive file or directory names is not allowed.")
    if not allow_read and any(part.startswith(".") for part in relative_parts):
        raise ValueError("Writing hidden paths is not allowed.")


def has_sensitive_name(lowered_parts):
    for part in lowered_parts:
        stem = Path(part).stem.lower()
        if stem in SENSITIVE_STEMS:
            return True
        words = [piece for piece in stem.replace("-", "_").split("_") if piece]
        if any(word in SENSITIVE_NAME_WORDS for word in words):
            return True
    return False


def check_allowed_text_file(path, project_root, allow_read):
    check_sensitive_path(path, project_root, allow_read=allow_read)
    check_not_symlink(path)
    check_text_extension(path)


def check_text_extension(path):
    if path.suffix.lower() not in TEXT_FILE_EXTENSIONS:
        raise ValueError(f"File type is not allowed: {path.suffix}")


def check_file_size(path, max_bytes):
    if path.stat().st_size > max_bytes:
        raise ValueError("File is too large.")


def check_not_symlink(path):
    if path.is_symlink():
        raise ValueError("Symbolic links are not allowed.")
    for parent in path.parents:
        if parent.is_symlink():
            raise ValueError("Symbolic link parent paths are not allowed.")

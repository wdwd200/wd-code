from pathlib import Path
import subprocess
import time

from wdcode.security.command_policy import check_command_allowed
from wdcode.security.paths import resolve_project_path
from wdcode.tools.base import Tool


DEFAULT_TIMEOUT_SECONDS = 30
MAX_TIMEOUT_SECONDS = 120


def create_command_tools(project_root):
    root = Path(project_root).resolve()
    return [
        Tool(
            name="run_command",
            description="Run a small allowlisted project command such as pytest or compileall.",
            parameters={
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "Allowlisted command to run.",
                    },
                    "cwd": {
                        "type": "string",
                        "description": "Project-relative working directory. Defaults to project root.",
                    },
                    "timeout": {
                        "type": "number",
                        "description": "Timeout in seconds. Defaults to 30 and is capped at 120.",
                    },
                },
                "required": ["command"],
                "additionalProperties": False,
            },
            execute=lambda arguments: run_command(root, arguments),
        )
    ]


def run_command(project_root, arguments):
    try:
        command = require_string(arguments, "command")
        cwd = resolve_command_cwd(project_root, arguments.get("cwd", "."))
        timeout = normalize_timeout(arguments.get("timeout", DEFAULT_TIMEOUT_SECONDS))
        decision = check_command_allowed(command)
        if not decision.allowed:
            return blocked_result(command, decision.reason)

        start = time.monotonic()
        try:
            completed = subprocess.run(
                list(decision.argv),
                cwd=str(cwd),
                capture_output=True,
                text=True,
                timeout=timeout,
                shell=False,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            return {
                "ok": False,
                "command": command,
                "exit_code": None,
                "stdout": exc.stdout or "",
                "stderr": exc.stderr or "",
                "duration_ms": elapsed_ms(start),
                "error": f"Command timed out after {timeout} seconds.",
            }

        return {
            "ok": completed.returncode == 0,
            "command": command,
            "exit_code": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
            "duration_ms": elapsed_ms(start),
        }
    except Exception as exc:
        return {
            "ok": False,
            "command": arguments.get("command") if isinstance(arguments, dict) else None,
            "exit_code": None,
            "stdout": "",
            "stderr": "",
            "duration_ms": 0,
            "error": str(exc),
        }


def require_string(arguments, name):
    value = arguments.get(name)
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a string.")
    return value


def resolve_command_cwd(project_root, cwd):
    if not isinstance(cwd, str):
        raise ValueError("cwd must be a string.")
    path = resolve_project_path(project_root, cwd)
    if not path.exists():
        raise FileNotFoundError(f"cwd does not exist: {cwd}")
    if not path.is_dir():
        raise NotADirectoryError(f"cwd is not a directory: {cwd}")
    return path


def normalize_timeout(timeout):
    if not isinstance(timeout, (int, float)) or isinstance(timeout, bool):
        raise ValueError("timeout must be a number.")
    if timeout <= 0:
        raise ValueError("timeout must be greater than zero.")
    return min(float(timeout), MAX_TIMEOUT_SECONDS)


def blocked_result(command, reason):
    return {
        "ok": False,
        "command": command,
        "exit_code": None,
        "stdout": "",
        "stderr": "",
        "duration_ms": 0,
        "error": reason,
    }


def elapsed_ms(start):
    return int((time.monotonic() - start) * 1000)

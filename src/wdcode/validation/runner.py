import subprocess
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from wdcode.security.command_policy import check_command_allowed


DEFAULT_VALIDATION_COMMANDS = ["python -m pytest"]


@dataclass(frozen=True)
class ValidationCommandResult:
    command: str
    ok: bool
    exit_code: int | None
    stdout: str
    stderr: str
    duration_ms: int
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ValidationReport:
    ok: bool
    results: list[ValidationCommandResult] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "results": [result.to_dict() for result in self.results],
        }


def run_validation(project_root: str | Path, commands: list[str] | None = None, timeout: int = 60, trace_writer=None) -> ValidationReport:
    root = Path(project_root).resolve()
    validation_commands = list(commands) if commands is not None else list(DEFAULT_VALIDATION_COMMANDS)
    results = []

    _write_trace(trace_writer, "validation_started", {"commands": validation_commands})
    for command in validation_commands:
        result = _run_validation_command(root, command, timeout)
        results.append(result)
        _write_trace(trace_writer, "validation_command_finished", result.to_dict())

    report = ValidationReport(
        ok=all(result.ok for result in results),
        results=results,
    )
    _write_trace(trace_writer, "validation_finished", report.to_dict())
    return report


def _run_validation_command(project_root: Path, command: str, timeout: int) -> ValidationCommandResult:
    start = time.monotonic()

    try:
        if not project_root.exists():
            return _failure(command, elapsed_ms(start), f"Project root does not exist: {project_root}")
        if not project_root.is_dir():
            return _failure(command, elapsed_ms(start), f"Project root is not a directory: {project_root}")

        decision = check_command_allowed(command)
        if not decision.allowed:
            return _failure(command, elapsed_ms(start), decision.reason)

        completed = subprocess.run(
            list(decision.argv),
            cwd=str(project_root),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            shell=False,
            check=False,
        )
        return ValidationCommandResult(
            command=command,
            ok=completed.returncode == 0,
            exit_code=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
            duration_ms=elapsed_ms(start),
            error=None,
        )
    except subprocess.TimeoutExpired as exc:
        return ValidationCommandResult(
            command=command,
            ok=False,
            exit_code=None,
            stdout=_normalize_output(exc.stdout),
            stderr=_normalize_output(exc.stderr),
            duration_ms=elapsed_ms(start),
            error=f"Command timed out after {timeout} seconds.",
        )
    except Exception as exc:
        return _failure(command, elapsed_ms(start), str(exc))


def _failure(command: str, duration_ms: int, error: str) -> ValidationCommandResult:
    return ValidationCommandResult(
        command=command,
        ok=False,
        exit_code=None,
        stdout="",
        stderr="",
        duration_ms=duration_ms,
        error=error,
    )


def elapsed_ms(start):
    return int((time.monotonic() - start) * 1000)


def _normalize_output(output):
    if output is None:
        return ""
    if isinstance(output, bytes):
        return output.decode("utf-8", errors="replace")
    return str(output)


def _write_trace(trace_writer, event_type, payload):
    if trace_writer is not None:
        trace_writer.write_event(event_type, payload)

from dataclasses import dataclass, field
from typing import Any

from wdcode.validation.loop import (
    run_validation_loop,
    validation_loop_report_to_dict,
)


SENSITIVE_KEY_PARTS = (
    "api_key",
    "apikey",
    "authorization",
    "credential",
    "key",
    "password",
    "secret",
    "token",
)


@dataclass(frozen=True)
class EvalTask:
    task_id: str
    name: str
    prompt: str
    validation_commands: list[str]
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.task_id or not self.task_id.strip():
            raise ValueError("task_id must not be empty.")
        if not self.name or not self.name.strip():
            raise ValueError("name must not be empty.")
        if not self.prompt or not self.prompt.strip():
            raise ValueError("prompt must not be empty.")
        if not self.validation_commands:
            raise ValueError("validation_commands must not be empty.")
        if not all(isinstance(command, str) and command.strip() for command in self.validation_commands):
            raise ValueError("validation_commands must contain non-empty strings.")


@dataclass(frozen=True)
class EvalResult:
    task_id: str
    ok: bool
    validation_report: dict[str, Any]
    metadata: dict[str, Any] = field(default_factory=dict)


def run_eval_task(
    *,
    task: EvalTask,
    project_root,
    validation_policy=None,
    trace_writer=None,
) -> EvalResult:
    validation_report = run_validation_loop(
        project_root=project_root,
        commands=list(task.validation_commands),
        policy=validation_policy,
        trace_writer=trace_writer,
    )
    validation_report_dict = validation_loop_report_to_dict(validation_report)
    return EvalResult(
        task_id=task.task_id,
        ok=validation_report.ok,
        validation_report=validation_report_dict,
        metadata=_safe_value(
            {
                "task_name": task.name,
                "validation_command_count": len(task.validation_commands),
                "final_status": validation_report.final_status,
                "task_metadata": task.metadata,
            }
        ),
    )


def eval_task_to_dict(task: EvalTask) -> dict[str, Any]:
    return {
        "task_id": task.task_id,
        "name": task.name,
        "prompt": task.prompt,
        "validation_commands": list(task.validation_commands),
        "metadata": _safe_value(task.metadata),
    }


def eval_result_to_dict(result: EvalResult) -> dict[str, Any]:
    return {
        "task_id": result.task_id,
        "ok": bool(result.ok),
        "validation_report": _safe_value(result.validation_report),
        "metadata": _safe_value(result.metadata),
    }


def _safe_value(value):
    if isinstance(value, dict):
        safe = {}
        for key, item in value.items():
            key_text = str(key)
            if _is_sensitive_key(key_text):
                safe[key_text] = "[redacted]"
            else:
                safe[key_text] = _safe_value(item)
        return safe
    if isinstance(value, list):
        return [_safe_value(item) for item in value]
    if isinstance(value, tuple):
        return [_safe_value(item) for item in value]
    if isinstance(value, str) and len(value) > 4000:
        return value[:3970].rstrip() + "\n[TRUNCATED: eval_metadata]"
    return value


def _is_sensitive_key(key: str) -> bool:
    lowered = key.lower()
    return any(part in lowered for part in SENSITIVE_KEY_PARTS)

from dataclasses import dataclass, field
from typing import Any

from wdcode.validation.discovery import discover_validation_plan
from wdcode.validation.runner import ValidationReport, run_validation


DEFAULT_OUTPUT_PREVIEW_CHARS = 4000
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
class ValidationLoopPolicy:
    max_attempts: int = 1
    allow_repair: bool = False
    output_preview_chars: int = DEFAULT_OUTPUT_PREVIEW_CHARS

    def __post_init__(self):
        if self.max_attempts <= 0:
            raise ValueError("max_attempts must be greater than 0.")
        if self.output_preview_chars <= 0:
            raise ValueError("output_preview_chars must be greater than 0.")


@dataclass(frozen=True)
class RepairRequest:
    attempt: int
    failed_commands: list[str]
    failure_summary: str
    prompt: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ValidationLoopReport:
    ok: bool
    attempts: int
    validation_reports: list[dict[str, Any]]
    repair_requests: list[dict[str, Any]]
    final_status: str
    metadata: dict[str, Any] = field(default_factory=dict)


def run_validation_loop(
    *,
    project_root,
    commands: list[str] | None = None,
    policy: ValidationLoopPolicy | None = None,
    trace_writer=None,
    repair_callback=None,
) -> ValidationLoopReport:
    policy = policy or ValidationLoopPolicy()
    attempts = 0
    validation_reports: list[dict[str, Any]] = []
    repair_requests: list[dict[str, Any]] = []

    try:
        plan = discover_validation_plan(
            project_root,
            explicit_commands=commands,
        )
        metadata = {
            "project_root": plan.project_root,
            "plan_source": plan.source,
            "commands": list(plan.commands),
            "plan_metadata": _safe_value(plan.metadata, policy.output_preview_chars),
        }
        _write_trace(
            trace_writer,
            "validation_loop_started",
            {
                "commands": list(plan.commands),
                "plan_source": plan.source,
                "policy": _policy_to_dict(policy),
            },
        )

        final_status = "failed"
        for attempt in range(1, policy.max_attempts + 1):
            attempts = attempt
            report = run_validation(
                plan.project_root,
                commands=plan.commands,
                trace_writer=trace_writer,
            )
            validation_reports.append(
                _validation_report_to_preview_dict(
                    report,
                    policy.output_preview_chars,
                )
            )
            _write_trace(
                trace_writer,
                "validation_loop_attempt_finished",
                {
                    "attempt": attempt,
                    "ok": report.ok,
                    "commands": list(plan.commands),
                },
            )

            if report.ok:
                final_status = "passed"
                loop_report = ValidationLoopReport(
                    ok=True,
                    attempts=attempts,
                    validation_reports=validation_reports,
                    repair_requests=repair_requests,
                    final_status=final_status,
                    metadata=metadata,
                )
                _write_trace(
                    trace_writer,
                    "validation_loop_finished",
                    validation_loop_report_to_dict(loop_report),
                )
                return loop_report

            if not policy.allow_repair:
                final_status = "failed"
                break

            repair_request = build_repair_request(
                validation_report=report,
                attempt=attempt,
                output_preview_chars=policy.output_preview_chars,
            )
            repair_request_dict = repair_request_to_dict(repair_request)
            repair_requests.append(repair_request_dict)

            should_retry = False
            if repair_callback is not None:
                try:
                    should_retry = bool(repair_callback(repair_request))
                except Exception as exc:
                    repair_request_dict["metadata"]["repair_callback_error"] = _preview_text(
                        str(exc),
                        policy.output_preview_chars,
                    )
                    should_retry = False

            final_status = "failed_after_repair"
            if not should_retry or attempt >= policy.max_attempts:
                break

        loop_report = ValidationLoopReport(
            ok=False,
            attempts=attempts,
            validation_reports=validation_reports,
            repair_requests=repair_requests,
            final_status=final_status,
            metadata=metadata,
        )
        _write_trace(
            trace_writer,
            "validation_loop_finished",
            validation_loop_report_to_dict(loop_report),
        )
        return loop_report
    except Exception as exc:
        loop_report = ValidationLoopReport(
            ok=False,
            attempts=attempts,
            validation_reports=[
                {
                    "ok": False,
                    "results": [
                        {
                            "command": "<validation-loop>",
                            "ok": False,
                            "exit_code": None,
                            "stdout": "",
                            "stdout_truncated": False,
                            "stderr": "",
                            "stderr_truncated": False,
                            "duration_ms": 0,
                            "error": _preview_text(
                                str(exc),
                                DEFAULT_OUTPUT_PREVIEW_CHARS,
                            ),
                            "error_truncated": False,
                        }
                    ],
                }
            ],
            repair_requests=repair_requests,
            final_status="failed",
            metadata={"error": _preview_text(str(exc), DEFAULT_OUTPUT_PREVIEW_CHARS)},
        )
        _write_trace(
            trace_writer,
            "validation_loop_finished",
            validation_loop_report_to_dict(loop_report),
        )
        return loop_report


def build_repair_request(
    *,
    validation_report,
    attempt: int,
    output_preview_chars: int = DEFAULT_OUTPUT_PREVIEW_CHARS,
) -> RepairRequest:
    if output_preview_chars <= 0:
        raise ValueError("output_preview_chars must be greater than 0.")

    results = list(getattr(validation_report, "results", []))
    failed_results = [result for result in results if not getattr(result, "ok", False)]
    failed_commands = [str(getattr(result, "command", "")) for result in failed_results]
    failure_summary = (
        f"{len(failed_results)} validation command(s) failed on attempt {attempt}."
        if failed_results
        else f"Validation failed on attempt {attempt}, but no failed command result was present."
    )
    prompt_lines = [
        "# Validation Repair Request",
        "",
        failure_summary,
        "",
        "Failed commands:",
    ]
    if failed_results:
        for result in failed_results:
            prompt_lines.extend(
                [
                    f"- command: {getattr(result, 'command', '')}",
                    f"  exit_code: {getattr(result, 'exit_code', None)}",
                    f"  stdout_preview: {_preview_text(getattr(result, 'stdout', ''), output_preview_chars)}",
                    f"  stderr_preview: {_preview_text(getattr(result, 'stderr', ''), output_preview_chars)}",
                    f"  error_preview: {_preview_text(getattr(result, 'error', '') or '', output_preview_chars)}",
                ]
            )
    else:
        prompt_lines.append("- none")

    return RepairRequest(
        attempt=attempt,
        failed_commands=failed_commands,
        failure_summary=failure_summary,
        prompt="\n".join(prompt_lines),
        metadata={
            "failed_command_count": len(failed_results),
            "output_preview_chars": output_preview_chars,
        },
    )


def validation_loop_report_to_dict(report: ValidationLoopReport) -> dict[str, Any]:
    return {
        "ok": bool(report.ok),
        "attempts": int(report.attempts),
        "validation_reports": _safe_value(
            report.validation_reports,
            DEFAULT_OUTPUT_PREVIEW_CHARS,
        ),
        "repair_requests": _safe_value(
            report.repair_requests,
            DEFAULT_OUTPUT_PREVIEW_CHARS,
        ),
        "final_status": str(report.final_status),
        "metadata": _safe_value(report.metadata, DEFAULT_OUTPUT_PREVIEW_CHARS),
    }


def repair_request_to_dict(request: RepairRequest) -> dict[str, Any]:
    return {
        "attempt": int(request.attempt),
        "failed_commands": list(request.failed_commands),
        "failure_summary": str(request.failure_summary),
        "prompt": str(request.prompt),
        "metadata": _safe_value(request.metadata, DEFAULT_OUTPUT_PREVIEW_CHARS),
    }


def _validation_report_to_preview_dict(
    report: ValidationReport,
    max_chars: int,
) -> dict[str, Any]:
    return {
        "ok": bool(report.ok),
        "results": [
            _validation_result_to_preview_dict(result, max_chars)
            for result in report.results
        ],
    }


def _validation_result_to_preview_dict(result, max_chars: int) -> dict[str, Any]:
    stdout, stdout_truncated = _preview_with_truncation(result.stdout, max_chars)
    stderr, stderr_truncated = _preview_with_truncation(result.stderr, max_chars)
    error, error_truncated = _preview_with_truncation(result.error or "", max_chars)
    return {
        "command": result.command,
        "ok": bool(result.ok),
        "exit_code": result.exit_code,
        "stdout": stdout,
        "stdout_truncated": stdout_truncated,
        "stderr": stderr,
        "stderr_truncated": stderr_truncated,
        "duration_ms": int(result.duration_ms),
        "error": error or None,
        "error_truncated": error_truncated,
    }


def _preview_with_truncation(value, max_chars: int) -> tuple[str, bool]:
    text = _redact_sensitive_text(_strip_stack_trace_text(_normalize_text(value)))
    if len(text) <= max_chars:
        return text, False
    marker = "\n[TRUNCATED: validation_output]"
    budget = max(0, max_chars - len(marker))
    return text[:budget].rstrip() + marker, True


def _preview_text(value, max_chars: int) -> str:
    return _preview_with_truncation(value, max_chars)[0]


def _normalize_text(value) -> str:
    if value is None:
        return ""
    return str(value)


def _strip_stack_trace_text(text: str) -> str:
    text = text.replace("Traceback (most recent call last):", "[stack trace omitted]")
    text = text.replace("Traceback", "[stack trace omitted]")
    return text


def _redact_sensitive_text(text: str) -> str:
    redacted = text.replace(".env", "[sensitive-file]")
    for marker in ("api_key", "API_KEY", "authorization", "Authorization"):
        redacted = redacted.replace(marker, "[redacted]")
    return redacted


def _safe_value(value, max_chars: int):
    if isinstance(value, dict):
        safe = {}
        for key, item in value.items():
            key_text = str(key)
            if _is_sensitive_key(key_text):
                safe[key_text] = "[redacted]"
            else:
                safe[key_text] = _safe_value(item, max_chars)
        return safe
    if isinstance(value, list):
        return [_safe_value(item, max_chars) for item in value]
    if isinstance(value, tuple):
        return [_safe_value(item, max_chars) for item in value]
    if isinstance(value, str):
        return _preview_text(value, max_chars)
    return value


def _is_sensitive_key(key: str) -> bool:
    lowered = key.lower()
    return any(part in lowered for part in SENSITIVE_KEY_PARTS)


def _policy_to_dict(policy: ValidationLoopPolicy) -> dict[str, Any]:
    return {
        "max_attempts": policy.max_attempts,
        "allow_repair": policy.allow_repair,
        "output_preview_chars": policy.output_preview_chars,
    }


def _write_trace(trace_writer, event_type, payload):
    if trace_writer is not None:
        trace_writer.write_event(event_type, payload)

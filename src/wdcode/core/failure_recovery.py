from dataclasses import dataclass, field
from typing import Any, Callable, Literal


FailureComponent = Literal["model", "tool", "validation", "runtime", "unknown"]
FailureCategory = Literal[
    "transient",
    "rate_limit",
    "timeout",
    "tool_error",
    "validation_error",
    "permission_error",
    "invalid_request",
    "unknown",
]

MAX_MESSAGE_CHARS = 1000
MAX_METADATA_STRING_CHARS = 500
MAX_VALIDATION_OUTPUT_CHARS = 1000
SENSITIVE_KEY_PARTS = (
    "api_key",
    "apikey",
    "authorization",
    "credential",
    "env",
    "key",
    "password",
    "secret",
    "token",
)


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 2
    retry_transient: bool = True
    retry_timeouts: bool = True
    retry_rate_limits: bool = True
    retry_tool_errors: bool = False

    def __post_init__(self):
        if self.max_attempts <= 0:
            raise ValueError("max_attempts must be greater than zero.")


@dataclass(frozen=True)
class FailureEvent:
    component: FailureComponent
    category: FailureCategory
    message: str
    exception_type: str | None
    attempt: int
    max_attempts: int
    retryable: bool
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class FailureReport:
    events: list[FailureEvent]
    final_status: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RetryResult:
    value: Any
    report: FailureReport


def classify_exception(
    exc: BaseException,
    *,
    component: FailureComponent = "unknown",
    attempt: int = 1,
    max_attempts: int = 1,
    metadata: dict[str, Any] | None = None,
) -> FailureEvent:
    category = _category_for_exception(exc, component=component)
    return FailureEvent(
        component=component,
        category=category,
        message=_exception_message(exc),
        exception_type=type(exc).__name__,
        attempt=attempt,
        max_attempts=max_attempts,
        retryable=attempt < max_attempts and category in {"timeout", "transient", "rate_limit", "tool_error"},
        metadata=_safe_metadata(metadata),
    )


def should_retry(event: FailureEvent, policy: RetryPolicy) -> bool:
    if event.attempt >= policy.max_attempts:
        return False
    if event.category == "timeout":
        return policy.retry_timeouts
    if event.category == "transient":
        return policy.retry_transient
    if event.category == "rate_limit":
        return policy.retry_rate_limits
    if event.category == "tool_error":
        return policy.retry_tool_errors
    return False


def call_with_retries(
    func: Callable[[], Any],
    *,
    component: FailureComponent,
    policy: RetryPolicy | None = None,
    metadata: dict[str, Any] | None = None,
) -> RetryResult:
    retry_policy = policy or RetryPolicy()
    events: list[FailureEvent] = []

    for attempt in range(1, retry_policy.max_attempts + 1):
        try:
            value = func()
            return RetryResult(
                value=value,
                report=FailureReport(
                    events=events,
                    final_status="success",
                    metadata=_safe_metadata(metadata),
                ),
            )
        except Exception as exc:
            event = classify_exception(
                exc,
                component=component,
                attempt=attempt,
                max_attempts=retry_policy.max_attempts,
                metadata=metadata,
            )
            retryable = should_retry(event, retry_policy)
            event = FailureEvent(
                component=event.component,
                category=event.category,
                message=event.message,
                exception_type=event.exception_type,
                attempt=event.attempt,
                max_attempts=event.max_attempts,
                retryable=retryable,
                metadata=event.metadata,
            )
            events.append(event)
            if not retryable:
                report = FailureReport(
                    events=events,
                    final_status="failed",
                    metadata=_safe_metadata(metadata),
                )
                setattr(exc, "failure_report", report)
                raise

    report = FailureReport(
        events=events,
        final_status="failed",
        metadata=_safe_metadata(metadata),
    )
    last_exc = RuntimeError("Retry attempts were exhausted.")
    setattr(last_exc, "failure_report", report)
    raise last_exc


def build_validation_failure_event(
    *,
    command: str,
    returncode: int | None,
    output_preview: str | None = None,
    attempt: int = 1,
    max_attempts: int = 1,
) -> FailureEvent:
    metadata = {
        "command": _preview_text(command, max_chars=MAX_METADATA_STRING_CHARS),
        "returncode": returncode,
    }
    if output_preview is not None:
        metadata["output_preview"] = _preview_text(
            output_preview,
            max_chars=MAX_VALIDATION_OUTPUT_CHARS,
        )
    return FailureEvent(
        component="validation",
        category="validation_error",
        message="Validation command failed.",
        exception_type=None,
        attempt=attempt,
        max_attempts=max_attempts,
        retryable=False,
        metadata=_safe_metadata(metadata),
    )


def failure_event_to_dict(event: FailureEvent) -> dict[str, Any]:
    return {
        "component": event.component,
        "category": event.category,
        "message": _preview_text(event.message, max_chars=MAX_MESSAGE_CHARS),
        "exception_type": event.exception_type,
        "attempt": event.attempt,
        "max_attempts": event.max_attempts,
        "retryable": event.retryable,
        "metadata": _safe_metadata(event.metadata),
    }


def failure_report_to_dict(report: FailureReport) -> dict[str, Any]:
    return {
        "events": [failure_event_to_dict(event) for event in report.events],
        "final_status": _preview_text(report.final_status, max_chars=MAX_METADATA_STRING_CHARS),
        "metadata": _safe_metadata(report.metadata),
    }


def _category_for_exception(exc: BaseException, *, component: FailureComponent) -> FailureCategory:
    exception_name = type(exc).__name__.lower()
    exception_message = str(exc).lower()
    if "ratelimit" in exception_name or "rate_limit" in exception_name:
        return "rate_limit"
    if "rate limit" in exception_message:
        return "rate_limit"
    if isinstance(exc, TimeoutError):
        return "timeout"
    if isinstance(exc, ConnectionError):
        return "transient"
    if isinstance(exc, PermissionError):
        return "permission_error"
    if isinstance(exc, (ValueError, TypeError)):
        return "invalid_request"
    if isinstance(exc, RuntimeError) and component == "tool":
        return "tool_error"
    return "unknown"


def _safe_metadata(value):
    if value is None:
        return {}
    if isinstance(value, dict):
        safe = {}
        for key, item in value.items():
            key_text = str(key)
            if _is_sensitive_key(key_text):
                safe[key_text] = "[REDACTED]"
            else:
                safe[key_text] = _safe_metadata_value(
                    item,
                    max_chars=_metadata_string_limit(key_text),
                )
        return safe
    return {}


def _safe_metadata_value(value, *, max_chars=MAX_METADATA_STRING_CHARS):
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return _preview_text(value, max_chars=max_chars)
    if isinstance(value, dict):
        return _safe_metadata(value)
    if isinstance(value, (list, tuple)):
        return [_safe_metadata_value(item, max_chars=max_chars) for item in value[:20]]
    return _preview_text(str(value), max_chars=max_chars)


def _metadata_string_limit(key: str) -> int:
    if key == "output_preview":
        return MAX_VALIDATION_OUTPUT_CHARS
    return MAX_METADATA_STRING_CHARS


def _is_sensitive_key(key: str) -> bool:
    lowered = key.lower()
    return any(part in lowered for part in SENSITIVE_KEY_PARTS)


def _preview_text(text: str, *, max_chars: int) -> str:
    compacted = " ".join(str(text).split())
    if len(compacted) <= max_chars:
        return compacted
    return compacted[:max_chars].rstrip()


def _exception_message(exc: BaseException) -> str:
    lines = [line.strip() for line in str(exc).splitlines() if line.strip()]
    for line in reversed(lines):
        if not line.startswith("Traceback") and not line.startswith("File "):
            return _preview_text(line, max_chars=MAX_MESSAGE_CHARS)
    return _preview_text(str(exc), max_chars=MAX_MESSAGE_CHARS)

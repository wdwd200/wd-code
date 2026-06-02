import copy
from dataclasses import dataclass
from typing import Any


TRUNCATION_MARKER = "\n[TRUNCATED: recovery_summary]"


@dataclass(frozen=True)
class RecoverySummary:
    summary: str
    source_message_count: int
    recent_message_count: int
    metadata: dict[str, Any]


def split_messages_for_recovery(
    messages: list[dict],
    *,
    keep_recent_messages: int = 12,
) -> tuple[list[dict], list[dict]]:
    if keep_recent_messages <= 0:
        raise ValueError("keep_recent_messages must be greater than zero.")

    copied = copy.deepcopy(messages)
    if len(copied) <= keep_recent_messages:
        return [], copied
    return copied[:-keep_recent_messages], copied[-keep_recent_messages:]


def build_recovery_summary(
    messages: list[dict],
    *,
    max_summary_chars: int = 4000,
    keep_recent_messages: int = 12,
) -> RecoverySummary | None:
    if max_summary_chars <= 0:
        raise ValueError("max_summary_chars must be greater than zero.")
    if keep_recent_messages <= 0:
        raise ValueError("keep_recent_messages must be greater than zero.")

    old_messages, recent_messages = split_messages_for_recovery(
        messages,
        keep_recent_messages=keep_recent_messages,
    )
    if not old_messages:
        return None

    summary = "\n".join(_summary_lines(old_messages, len(recent_messages)))
    summary, truncated = _apply_summary_budget(summary, max_summary_chars)
    return RecoverySummary(
        summary=summary,
        source_message_count=len(old_messages),
        recent_message_count=len(recent_messages),
        metadata={
            "generated_by": "rule_based",
            "truncated": truncated,
        },
    )


def _summary_lines(old_messages: list[dict], recent_message_count: int) -> list[str]:
    user_requests = []
    assistant_progress = []
    tool_results = []

    for index, message in enumerate(old_messages, start=1):
        role = message.get("role", "unknown")
        preview = _message_preview(message)
        if role == "user":
            user_requests.append(f"- [{index}] {preview}")
        elif role == "assistant":
            assistant_progress.append(f"- [{index}] {preview}")
        elif role == "tool":
            tool_results.append(f"- [{index}] {preview}")

    return [
        "# Recovery Summary",
        "",
        f"Earlier conversation contained {len(old_messages)} messages.",
        f"Recent messages kept outside this summary: {recent_message_count}.",
        "",
        "## User requests",
        *(_non_empty_lines(user_requests)),
        "",
        "## Assistant/tool progress",
        *(_non_empty_lines(assistant_progress)),
        "",
        "## Tool results",
        *(_non_empty_lines(tool_results)),
    ]


def _non_empty_lines(lines: list[str]) -> list[str]:
    if lines:
        return lines
    return ["- none"]


def _message_preview(message: dict) -> str:
    role = message.get("role", "unknown")
    content = message.get("content")
    if content is None and message.get("tool_calls"):
        content = f"{len(message.get('tool_calls') or [])} tool call(s)"
    if role == "tool":
        name = message.get("name") or "unknown_tool"
        content = f"{name}: {content}"
    return _compact_text(str(content or ""))


def _compact_text(text: str, *, max_chars: int = 240) -> str:
    compacted = " ".join(text.split())
    if len(compacted) <= max_chars:
        return compacted
    return compacted[: max_chars - 3].rstrip() + "..."


def _apply_summary_budget(text: str, max_summary_chars: int) -> tuple[str, bool]:
    if len(text) <= max_summary_chars:
        return text, False

    content_limit = max_summary_chars - len(TRUNCATION_MARKER)
    if content_limit <= 0:
        return TRUNCATION_MARKER, True
    return text[:content_limit].rstrip() + TRUNCATION_MARKER, True

import copy
import json
import re
from dataclasses import dataclass, field
from typing import Any


TRUNCATION_MARKER = "[TRUNCATED: conversation_compression]"
SUMMARY_TITLE = "# Compressed Conversation History"
DEFAULT_PREVIEW_CHARS = 240
MAX_METADATA_STRING_CHARS = 500
PATH_PATTERN = re.compile(
    r"(?<![\w./\\-])"
    r"((?:[A-Za-z0-9_.-]+[\\/])+[A-Za-z0-9_.-]+"
    r"\.(?:py|md|txt|json|toml|yaml|yml|ini|cfg|lock|html|css|js|ts|tsx|jsx))"
    r"(?![\w/\\-])"
)
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
class CompressionPolicy:
    trigger_message_count: int = 80
    keep_recent_messages: int = 20
    max_summary_chars: int = 6000
    max_tool_result_chars: int = 1000
    max_key_files: int = 30

    def __post_init__(self):
        for name in (
            "trigger_message_count",
            "keep_recent_messages",
            "max_summary_chars",
            "max_tool_result_chars",
            "max_key_files",
        ):
            if getattr(self, name) <= 0:
                raise ValueError(f"{name} must be greater than zero.")


@dataclass(frozen=True)
class ConversationCompression:
    summary: str
    source_message_count: int
    kept_recent_message_count: int
    compressed_message_count: int
    key_files: list[str] = field(default_factory=list)
    key_tool_results: list[dict[str, Any]] = field(default_factory=list)
    source_range: dict[str, int] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


def build_conversation_compression(
    messages: list[dict],
    *,
    recovery_summary: dict[str, Any] | None = None,
    policy: CompressionPolicy | None = None,
) -> ConversationCompression | None:
    compression_policy = policy or CompressionPolicy()
    source_messages = copy.deepcopy(messages)
    if len(source_messages) <= compression_policy.trigger_message_count:
        return None

    old_messages, recent_messages = split_messages_for_compression(
        source_messages,
        keep_recent_messages=compression_policy.keep_recent_messages,
    )
    if not old_messages:
        return None

    key_files = extract_key_files_from_messages(
        old_messages,
        max_files=compression_policy.max_key_files,
    )
    key_tool_results = extract_key_tool_results(
        old_messages,
        max_result_chars=compression_policy.max_tool_result_chars,
    )
    source_range = {
        "start_index": 0,
        "end_index": len(old_messages) - 1,
    }
    summary, truncated = _build_summary_text(
        old_messages=old_messages,
        recent_messages=recent_messages,
        key_files=key_files,
        key_tool_results=key_tool_results,
        recovery_summary=recovery_summary,
        policy=compression_policy,
    )
    metadata = {
        "method": "deterministic-rule-based",
        "version": 1,
        "truncated": truncated,
        "used_recovery_summary": recovery_summary is not None,
    }

    return ConversationCompression(
        summary=summary,
        source_message_count=len(source_messages),
        kept_recent_message_count=len(recent_messages),
        compressed_message_count=len(old_messages),
        key_files=key_files,
        key_tool_results=key_tool_results,
        source_range=source_range,
        metadata=metadata,
    )


def split_messages_for_compression(
    messages: list[dict],
    *,
    keep_recent_messages: int = 20,
) -> tuple[list[dict], list[dict]]:
    if keep_recent_messages <= 0:
        raise ValueError("keep_recent_messages must be greater than zero.")
    copied = copy.deepcopy(messages)
    if len(copied) <= keep_recent_messages:
        return [], copied
    return copied[:-keep_recent_messages], copied[-keep_recent_messages:]


def extract_key_files_from_messages(
    messages: list[dict],
    *,
    max_files: int = 30,
) -> list[str]:
    if max_files <= 0:
        raise ValueError("max_files must be greater than zero.")

    paths: list[str] = []
    seen = set()
    for text in _iter_message_text_fragments(messages):
        for match in PATH_PATTERN.finditer(text):
            path = match.group(1).replace("\\", "/")
            if path not in seen:
                seen.add(path)
                paths.append(path)
                if len(paths) >= max_files:
                    return paths
    return paths


def extract_key_tool_results(
    messages: list[dict],
    *,
    max_results: int = 10,
    max_result_chars: int = 1000,
) -> list[dict[str, Any]]:
    if max_results <= 0:
        raise ValueError("max_results must be greater than zero.")
    if max_result_chars <= 0:
        raise ValueError("max_result_chars must be greater than zero.")

    results = []
    for message in copy.deepcopy(messages):
        if not _looks_like_tool_result(message):
            continue
        content_preview, truncated = _tool_content_preview(
            message.get("content", ""),
            max_chars=max_result_chars,
        )
        results.append(
            {
                "tool_call_id": message.get("tool_call_id"),
                "name": message.get("name"),
                "content_preview": content_preview,
                "truncated": truncated,
            }
        )
        if len(results) >= max_results:
            return results
    return results


def conversation_compression_to_dict(
    compression: ConversationCompression,
) -> dict[str, Any]:
    return {
        "summary": _preview_or_text(compression.summary),
        "source_message_count": compression.source_message_count,
        "kept_recent_message_count": compression.kept_recent_message_count,
        "compressed_message_count": compression.compressed_message_count,
        "key_files": list(compression.key_files),
        "key_tool_results": copy.deepcopy(compression.key_tool_results),
        "source_range": copy.deepcopy(compression.source_range),
        "metadata": _safe_metadata(compression.metadata),
    }


def conversation_compression_from_dict(
    data: dict[str, Any] | None,
) -> ConversationCompression | None:
    if data is None:
        return None
    if not isinstance(data, dict):
        raise ValueError("compression summary must be an object.")
    return ConversationCompression(
        summary=str(data.get("summary") or ""),
        source_message_count=int(data.get("source_message_count") or 0),
        kept_recent_message_count=int(data.get("kept_recent_message_count") or 0),
        compressed_message_count=int(data.get("compressed_message_count") or 0),
        key_files=[str(item) for item in data.get("key_files") or []],
        key_tool_results=copy.deepcopy(data.get("key_tool_results") or []),
        source_range=copy.deepcopy(data.get("source_range") or {}),
        metadata=_safe_metadata(data.get("metadata") or {}),
    )


def _build_summary_text(
    *,
    old_messages,
    recent_messages,
    key_files,
    key_tool_results,
    recovery_summary,
    policy,
):
    lines = [
        SUMMARY_TITLE,
        "",
        (
            f"Source: messages 0-{len(old_messages) - 1} compressed; "
            f"recent {len(recent_messages)} messages kept verbatim."
        ),
        "Method: deterministic-rule-based.",
    ]
    if recovery_summary is not None:
        lines.append("Based partly on existing recovery summary.")
    lines.extend(
        [
            "",
            "## Earlier user requests",
            *_message_preview_lines(old_messages, role="user"),
            "",
            "## Assistant progress",
            *_message_preview_lines(old_messages, role="assistant"),
            "",
            "## Key tool results",
            *_tool_result_lines(key_tool_results),
            "",
            "## Key files",
            *_key_file_lines(key_files),
            "",
            "## Source markers",
            f"- source_message_count: {len(old_messages) + len(recent_messages)}",
            f"- compressed_message_count: {len(old_messages)}",
            f"- kept_recent_message_count: {len(recent_messages)}",
        ]
    )
    return _apply_summary_budget("\n".join(lines), policy.max_summary_chars)


def _message_preview_lines(messages, *, role):
    lines = []
    for message in messages:
        if message.get("role") != role:
            continue
        content = str(message.get("content") or "")
        if role == "assistant" and not content.strip():
            content = "assistant requested or handled tool calls"
        lines.append(f"- {_preview_text(content)}")
        if len(lines) >= 12:
            break
    return lines or ["- none"]


def _tool_result_lines(key_tool_results):
    if not key_tool_results:
        return ["- none"]
    lines = []
    for result in key_tool_results:
        name = result.get("name") or "unknown"
        preview = result.get("content_preview") or ""
        lines.append(f"- {name}: {_preview_text(preview)}")
    return lines


def _key_file_lines(key_files):
    return [f"- {path}" for path in key_files] or ["- none"]


def _iter_message_text_fragments(messages):
    for message in copy.deepcopy(messages):
        yield from _iter_value_text(message.get("content"))
        yield from _iter_value_text(message.get("tool_calls"))
        yield from _iter_value_text(message.get("function"))
        if _looks_like_tool_result(message):
            yield from _iter_value_text(message.get("content"))


def _iter_value_text(value):
    if value is None:
        return
    if isinstance(value, str):
        yield value
        parsed = _try_parse_json(value)
        if parsed is not None:
            yield from _iter_value_text(parsed)
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if _is_sensitive_key(str(key)):
                continue
            yield from _iter_value_text(item)
        return
    if isinstance(value, list):
        for item in value:
            yield from _iter_value_text(item)


def _looks_like_tool_result(message):
    return message.get("role") == "tool" or (
        "tool_call_id" in message and "content" in message
    )


def _tool_content_preview(content, *, max_chars):
    parsed = _try_parse_json(content) if isinstance(content, str) else None
    if isinstance(parsed, dict):
        value = {
            "ok": parsed.get("ok"),
            "error": _preview_text(str(parsed.get("error") or "")),
            "metadata": _safe_metadata(parsed.get("metadata") or {}),
            "data_preview": _preview_text(_json_preview(parsed.get("data"))),
        }
        text = json.dumps(value, ensure_ascii=False, sort_keys=True)
    else:
        text = str(content or "")
    return _preview_with_truncation(text, max_chars=max_chars)


def _apply_summary_budget(text, max_summary_chars):
    if len(text) <= max_summary_chars:
        return text, False
    suffix = f"\n{TRUNCATION_MARKER}"
    if max_summary_chars <= len(suffix):
        return TRUNCATION_MARKER, True
    return text[: max_summary_chars - len(suffix)].rstrip() + suffix, True


def _preview_with_truncation(text, *, max_chars):
    compacted = " ".join(str(text).split())
    if len(compacted) <= max_chars:
        return compacted, False
    return compacted[:max_chars].rstrip(), True


def _preview_text(text, *, max_chars=DEFAULT_PREVIEW_CHARS):
    return _preview_with_truncation(text, max_chars=max_chars)[0]


def _preview_or_text(text):
    return str(text)


def _json_preview(value):
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    except (TypeError, ValueError):
        return str(value)


def _try_parse_json(value):
    if not isinstance(value, str):
        return None
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return None


def _safe_metadata(value):
    if not isinstance(value, dict):
        return {}
    safe = {}
    for key, item in value.items():
        key_text = str(key)
        if _is_sensitive_key(key_text):
            safe[key_text] = "[REDACTED]"
        elif isinstance(item, str):
            safe[key_text] = _preview_text(item, max_chars=MAX_METADATA_STRING_CHARS)
        elif isinstance(item, (bool, int, float)) or item is None:
            safe[key_text] = item
        elif isinstance(item, dict):
            safe[key_text] = _safe_metadata(item)
        elif isinstance(item, list):
            safe[key_text] = [
                _preview_text(str(entry), max_chars=MAX_METADATA_STRING_CHARS)
                for entry in item[:20]
            ]
        else:
            safe[key_text] = _preview_text(str(item), max_chars=MAX_METADATA_STRING_CHARS)
    return safe


def _is_sensitive_key(key):
    lowered = str(key).lower()
    return any(part in lowered for part in SENSITIVE_KEY_PARTS)

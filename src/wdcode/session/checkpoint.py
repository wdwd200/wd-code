import copy
import json
import subprocess
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from wdcode.core.conversation import Conversation
from wdcode.session.store import validate_session_id


CHECKPOINT_VERSION = 1
DEFAULT_PREVIEW_CHARS = 500
SENSITIVE_ARGUMENT_KEYS = {
    "api_key",
    "apikey",
    "authorization",
    "credential",
    "credentials",
    "key",
    "password",
    "secret",
    "token",
}


@dataclass(frozen=True)
class TurnCheckpoint:
    checkpoint_id: str
    session_id: str
    turn_index: int
    created_at: str
    messages: list[dict[str, Any]]
    recovery_summary: dict[str, Any] | None
    context_snapshot: dict[str, Any] | None
    tool_call_snapshot: list[dict[str, Any]]
    file_change_snapshot: dict[str, Any]
    metadata: dict[str, Any]


class CheckpointStore:
    def __init__(self, root: Path | str):
        self.root = Path(root)

    def save(self, checkpoint: TurnCheckpoint) -> None:
        session_id = validate_session_id(checkpoint.session_id)
        checkpoint_id = validate_session_id(checkpoint.checkpoint_id)
        directory = self.root / session_id
        directory.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": CHECKPOINT_VERSION,
            "checkpoint_id": checkpoint_id,
            "session_id": session_id,
            "turn_index": checkpoint.turn_index,
            "created_at": checkpoint.created_at,
            "messages": copy.deepcopy(checkpoint.messages),
            "recovery_summary": copy.deepcopy(checkpoint.recovery_summary),
            "context_snapshot": copy.deepcopy(checkpoint.context_snapshot),
            "tool_call_snapshot": copy.deepcopy(checkpoint.tool_call_snapshot),
            "file_change_snapshot": copy.deepcopy(checkpoint.file_change_snapshot),
            "metadata": copy.deepcopy(checkpoint.metadata),
        }
        (directory / f"{checkpoint_id}.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def load(self, session_id: str, checkpoint_id: str) -> TurnCheckpoint | None:
        session_id = validate_session_id(session_id)
        checkpoint_id = validate_session_id(checkpoint_id)
        path = self.root / session_id / f"{checkpoint_id}.json"
        if not path.exists():
            return None

        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"Invalid checkpoint JSON for {session_id}/{checkpoint_id}.") from exc

        if payload.get("version") != CHECKPOINT_VERSION:
            raise ValueError(f"Unsupported checkpoint version for {session_id}/{checkpoint_id}.")
        return _checkpoint_from_payload(payload)

    def list_for_session(self, session_id: str) -> list[TurnCheckpoint]:
        session_id = validate_session_id(session_id)
        directory = self.root / session_id
        if not directory.exists():
            return []

        checkpoints = []
        for path in sorted(directory.glob("*.json"), key=lambda item: item.name):
            checkpoint = self.load(session_id, path.stem)
            if checkpoint is not None:
                checkpoints.append(checkpoint)
        return sorted(checkpoints, key=lambda item: (item.created_at, item.checkpoint_id))

    def latest_for_session(self, session_id: str) -> TurnCheckpoint | None:
        checkpoints = self.list_for_session(session_id)
        if not checkpoints:
            return None
        return checkpoints[-1]


def build_turn_checkpoint(
    *,
    session_id: str,
    turn_index: int,
    messages: list[dict],
    recovery_summary: dict[str, Any] | None = None,
    context_snapshot: dict[str, Any] | None = None,
    tool_call_snapshot: list[dict[str, Any]] | None = None,
    file_change_snapshot: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> TurnCheckpoint:
    session_id = validate_session_id(session_id)
    if turn_index < 0:
        raise ValueError("turn_index must be greater than or equal to zero.")

    return TurnCheckpoint(
        checkpoint_id=create_checkpoint_id(),
        session_id=session_id,
        turn_index=turn_index,
        created_at=_utc_now(),
        messages=copy.deepcopy(messages),
        recovery_summary=copy.deepcopy(recovery_summary),
        context_snapshot=copy.deepcopy(context_snapshot),
        tool_call_snapshot=copy.deepcopy(tool_call_snapshot or []),
        file_change_snapshot=copy.deepcopy(file_change_snapshot or {}),
        metadata=copy.deepcopy(metadata or {}),
    )


def create_checkpoint_id() -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    suffix = uuid.uuid4().hex[:8]
    return f"{timestamp}-{suffix}"


def build_context_snapshot(context) -> dict[str, Any] | None:
    if context is None:
        return None

    text = getattr(context, "text", "") or ""
    metadata = getattr(context, "metadata", None)
    preview, truncated = _preview(text)
    return {
        "has_text": bool(text),
        "char_count": len(text),
        "text_preview": preview,
        "text_truncated": truncated,
        "metadata": copy.deepcopy(metadata) if metadata is not None else None,
    }


def build_tool_call_snapshot(tool_calls: list[dict]) -> list[dict[str, Any]]:
    snapshots = []
    for tool_call in copy.deepcopy(tool_calls or []):
        function = tool_call.get("function") or {}
        arguments = function.get("arguments", "")
        arguments_preview, arguments_truncated = _arguments_preview(arguments)
        snapshots.append(
            {
                "tool_call_id": tool_call.get("id"),
                "name": function.get("name", ""),
                "arguments_preview": arguments_preview,
                "arguments_truncated": arguments_truncated,
            }
        )
    return snapshots


def build_file_change_snapshot(project_root: Path | str | None) -> dict[str, Any]:
    if project_root is None:
        return _unavailable_file_snapshot("project_root_not_provided")

    root = Path(project_root)
    if not root.exists() or not root.is_dir():
        return _unavailable_file_snapshot("project_root_unavailable")

    repo_check = _run_git(root, ["rev-parse", "--is-inside-work-tree"])
    if not repo_check["ok"] or repo_check["stdout"].strip().lower() != "true":
        return _unavailable_file_snapshot("not_git_repository", error=repo_check["error"])

    status = _run_git(root, ["status", "--short"])
    diff = _run_git(root, ["diff", "--name-only"])
    cached = _run_git(root, ["diff", "--cached", "--name-only"])
    snapshot = {
        "available": True,
        "status_short": status["stdout"].splitlines() if status["ok"] else [],
        "diff_names": diff["stdout"].splitlines() if diff["ok"] else [],
        "cached_diff_names": cached["stdout"].splitlines() if cached["ok"] else [],
        "errors": {},
    }
    if not status["ok"]:
        snapshot["errors"]["status_short"] = status["error"]
    if not diff["ok"]:
        snapshot["errors"]["diff_names"] = diff["error"]
    if not cached["ok"]:
        snapshot["errors"]["cached_diff_names"] = cached["error"]
    return snapshot


def restore_conversation_from_checkpoint(checkpoint: TurnCheckpoint):
    return Conversation.from_messages(
        checkpoint.messages,
        recovery_summary=checkpoint.recovery_summary,
    )


def _checkpoint_from_payload(payload: dict[str, Any]) -> TurnCheckpoint:
    try:
        return TurnCheckpoint(
            checkpoint_id=validate_session_id(payload["checkpoint_id"]),
            session_id=validate_session_id(payload["session_id"]),
            turn_index=payload["turn_index"],
            created_at=payload["created_at"],
            messages=copy.deepcopy(payload["messages"]),
            recovery_summary=copy.deepcopy(payload.get("recovery_summary")),
            context_snapshot=copy.deepcopy(payload.get("context_snapshot")),
            tool_call_snapshot=copy.deepcopy(payload.get("tool_call_snapshot") or []),
            file_change_snapshot=copy.deepcopy(payload.get("file_change_snapshot") or {}),
            metadata=copy.deepcopy(payload.get("metadata") or {}),
        )
    except (KeyError, TypeError) as exc:
        raise ValueError("Invalid checkpoint record.") from exc


def _arguments_preview(arguments: str) -> tuple[str, bool]:
    try:
        parsed = json.loads(arguments or "{}")
    except json.JSONDecodeError:
        return _preview(str(arguments or ""))

    sanitized = _redact_sensitive_values(parsed)
    return _preview(json.dumps(sanitized, ensure_ascii=False, sort_keys=True))


def _redact_sensitive_values(value):
    if isinstance(value, dict):
        redacted = {}
        for key, item in value.items():
            if str(key).lower() in SENSITIVE_ARGUMENT_KEYS:
                redacted[key] = "[REDACTED]"
            else:
                redacted[key] = _redact_sensitive_values(item)
        return redacted
    if isinstance(value, list):
        return [_redact_sensitive_values(item) for item in value]
    return value


def _preview(text: str, *, max_chars: int = DEFAULT_PREVIEW_CHARS) -> tuple[str, bool]:
    compacted = " ".join(str(text).split())
    if len(compacted) <= max_chars:
        return compacted, False
    return compacted[:max_chars].rstrip(), True


def _run_git(project_root: Path, args: list[str]) -> dict[str, Any]:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=project_root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"ok": False, "stdout": "", "error": str(exc)}

    if result.returncode != 0:
        return {"ok": False, "stdout": result.stdout, "error": result.stderr.strip()}
    return {"ok": True, "stdout": result.stdout, "error": ""}


def _unavailable_file_snapshot(reason: str, *, error: str = "") -> dict[str, Any]:
    snapshot = {
        "available": False,
        "reason": reason,
        "status_short": [],
        "diff_names": [],
        "cached_diff_names": [],
    }
    if error:
        snapshot["error"] = error
    return snapshot


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()

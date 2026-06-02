import copy
import json
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SESSION_VERSION = 1
SESSION_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")


@dataclass(frozen=True)
class SessionRecord:
    session_id: str
    messages: list[dict[str, Any]]
    created_at: str
    updated_at: str
    metadata: dict[str, Any]


def create_session_id() -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    suffix = uuid.uuid4().hex[:8]
    return f"{timestamp}-{suffix}"


def validate_session_id(session_id: str) -> str:
    if not session_id:
        raise ValueError("session_id must not be empty.")
    if ".." in session_id:
        raise ValueError("session_id must not contain '..'.")
    if "/" in session_id or "\\" in session_id:
        raise ValueError("session_id must not contain path separators.")
    if not SESSION_ID_PATTERN.fullmatch(session_id):
        raise ValueError("session_id may only contain letters, numbers, hyphens, and underscores.")
    return session_id


class SessionStore:
    def __init__(self, root: Path | str):
        self.root = Path(root)

    def save(self, record: SessionRecord) -> None:
        session_id = validate_session_id(record.session_id)
        self.root.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": SESSION_VERSION,
            "session_id": session_id,
            "created_at": record.created_at,
            "updated_at": record.updated_at,
            "messages": copy.deepcopy(record.messages),
            "metadata": copy.deepcopy(record.metadata),
        }
        self._path_for(session_id).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def load(self, session_id: str) -> SessionRecord | None:
        session_id = validate_session_id(session_id)
        path = self._path_for(session_id)
        if not path.exists():
            return None

        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"Invalid session JSON for {session_id}.") from exc

        if payload.get("version") != SESSION_VERSION:
            raise ValueError(f"Unsupported session version for {session_id}.")

        try:
            return SessionRecord(
                session_id=validate_session_id(payload["session_id"]),
                messages=copy.deepcopy(payload["messages"]),
                created_at=payload["created_at"],
                updated_at=payload["updated_at"],
                metadata=copy.deepcopy(payload.get("metadata") or {}),
            )
        except (KeyError, TypeError) as exc:
            raise ValueError(f"Invalid session record for {session_id}.") from exc

    def exists(self, session_id: str) -> bool:
        return self._path_for(validate_session_id(session_id)).exists()

    def _path_for(self, session_id: str) -> Path:
        return self.root / f"{validate_session_id(session_id)}.json"

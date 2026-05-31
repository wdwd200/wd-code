import json
import re
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path


REDACTED = "[REDACTED]"
SENSITIVE_KEY_PARTS = ("api_key", "token", "secret", "password")
SENSITIVE_STRING_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9_-]+"),
    re.compile(r"Bearer\s+[A-Za-z0-9._-]+"),
)


class TraceWriter:
    def __init__(self, path):
        self.path = Path(path)

    def write_event(self, event_type: str, payload: dict) -> None:
        event = {
            "event_type": event_type,
            "timestamp": datetime.now(UTC).isoformat(),
            "payload": redact_secrets(payload),
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False) + "\n")


def redact_secrets(value):
    if isinstance(value, dict):
        redacted = {}
        for key, item in value.items():
            if _is_sensitive_key(key):
                redacted[key] = REDACTED
            else:
                redacted[key] = redact_secrets(item)
        return redacted
    if isinstance(value, list):
        return [redact_secrets(item) for item in value]
    if isinstance(value, tuple):
        return [redact_secrets(item) for item in value]
    if isinstance(value, str):
        return _redact_sensitive_strings(value)
    return deepcopy(value)


def _is_sensitive_key(key):
    lowered = str(key).lower()
    return any(part in lowered for part in SENSITIVE_KEY_PARTS)


def _redact_sensitive_strings(value):
    redacted = value
    for pattern in SENSITIVE_STRING_PATTERNS:
        redacted = pattern.sub(REDACTED, redacted)
    return redacted

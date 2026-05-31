from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ToolResult:
    ok: bool
    data: Any = None
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self):
        return {
            "ok": self.ok,
            "data": self.data,
            "error": self.error,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def success(cls, data=None, **metadata):
        return cls(ok=True, data=data, error=None, metadata=metadata)

    @classmethod
    def failure(cls, error, data=None, **metadata):
        return cls(ok=False, data=data, error=error, metadata=metadata)

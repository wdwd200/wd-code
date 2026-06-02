from dataclasses import dataclass


@dataclass(frozen=True)
class AssistantRoute:
    is_final: bool
    content: str
    tool_calls: tuple[dict, ...]
    raw_message: dict


def route_assistant_message(assistant_message: dict) -> AssistantRoute:
    tool_calls = tuple(assistant_message.get("tool_calls") or ())
    return AssistantRoute(
        is_final=not bool(tool_calls),
        content=assistant_message.get("content") or "",
        tool_calls=tool_calls,
        raw_message=assistant_message,
    )

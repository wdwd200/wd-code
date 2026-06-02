from dataclasses import dataclass
from pathlib import Path


TRUNCATION_MARKER = "\n\n[TRUNCATED]\n"


@dataclass(frozen=True)
class AgentsContext:
    path: str
    content: str
    truncated: bool = False


def load_agents_context(project_root: Path | str, *, max_chars: int = 12000) -> AgentsContext | None:
    if max_chars <= 0:
        raise ValueError("max_chars must be greater than zero.")

    root = Path(project_root).resolve()
    if not root.exists():
        raise ValueError(f"Project root does not exist: {project_root}")
    if not root.is_dir():
        raise ValueError(f"Project root is not a directory: {project_root}")

    agents_path = root / "AGENTS.md"
    if not agents_path.exists() or agents_path.is_dir():
        return None

    try:
        content = agents_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise ValueError(f"Could not read AGENTS.md: {exc}") from exc

    truncated = False
    if len(content) > max_chars:
        content = content[:max_chars].rstrip() + TRUNCATION_MARKER
        truncated = True

    return AgentsContext(path="AGENTS.md", content=content, truncated=truncated)


def format_agents_context(context: AgentsContext | None) -> str:
    if context is None:
        return "# AGENTS.md\n\nNo AGENTS.md found."

    truncated = "true" if context.truncated else "false"
    return (
        "# AGENTS.md\n\n"
        f"Path: {context.path}\n"
        f"Truncated: {truncated}\n\n"
        "```markdown\n"
        f"{context.content}\n"
        "```"
    )

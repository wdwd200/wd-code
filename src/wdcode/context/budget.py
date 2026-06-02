from dataclasses import dataclass


@dataclass(frozen=True)
class ContextBudget:
    max_total_chars: int = 20000
    max_agents_chars: int = 6000
    max_repo_map_chars: int = 8000
    max_recent_files_chars: int = 3000
    max_relevant_files_chars: int = 4000

    def __post_init__(self):
        for field_name, value in self.__dict__.items():
            if value <= 0:
                raise ValueError(f"{field_name} must be greater than zero.")


def apply_char_budget(
    text: str,
    max_chars: int,
    *,
    label: str,
) -> tuple[str, bool]:
    if max_chars <= 0:
        raise ValueError("max_chars must be greater than zero.")

    if len(text) <= max_chars:
        return text, False

    marker = f"\n[TRUNCATED: {label}]"
    content_limit = max_chars - len(marker)
    if content_limit <= 0:
        return marker, True

    return text[:content_limit].rstrip() + marker, True


def apply_context_budget(
    *,
    agents_text: str,
    repo_map_text: str,
    relevant_files_text: str,
    budget: ContextBudget,
    recent_files_text: str = "",
) -> tuple[str, dict[str, bool]]:
    agents_text, agents_truncated = apply_char_budget(
        agents_text,
        budget.max_agents_chars,
        label="agents",
    )
    repo_map_text, repo_map_truncated = apply_char_budget(
        repo_map_text,
        budget.max_repo_map_chars,
        label="repo_map",
    )
    recent_files_text, recent_files_truncated = apply_char_budget(
        recent_files_text,
        budget.max_recent_files_chars,
        label="recent_files",
    )
    relevant_files_text, relevant_files_truncated = apply_char_budget(
        relevant_files_text,
        budget.max_relevant_files_chars,
        label="relevant_files",
    )

    context_text = "\n\n".join(
        [
            "# Project Context",
            "## AGENTS.md",
            agents_text,
            "## Repo Map",
            repo_map_text,
            "## Recent Files",
            recent_files_text,
            "## Relevant Files",
            relevant_files_text,
        ]
    )
    context_text, total_truncated = apply_char_budget(
        context_text,
        budget.max_total_chars,
        label="project_context",
    )

    return context_text, {
        "agents_truncated": agents_truncated,
        "repo_map_truncated": repo_map_truncated,
        "recent_files_truncated": recent_files_truncated,
        "relevant_files_truncated": relevant_files_truncated,
        "total_truncated": total_truncated,
    }

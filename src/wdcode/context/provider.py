from dataclasses import dataclass
from pathlib import Path

from wdcode.context.agents import format_agents_context, load_agents_context
from wdcode.context.budget import ContextBudget, apply_context_budget
from wdcode.context.repo_map import build_repo_map, format_repo_map
from wdcode.context.retrieval import format_retrieval_candidates, retrieve_relevant_files


@dataclass(frozen=True)
class ContextBundle:
    text: str = ""
    metadata: dict[str, object] | None = None


class ContextProvider:
    def __init__(self, project_root=None, *, max_retrieval_results=8, budget=None):
        self.project_root = Path(project_root).resolve() if project_root is not None else None
        self.max_retrieval_results = max_retrieval_results
        self.budget = budget or ContextBudget()

    def build(self, *, user_input: str, conversation) -> ContextBundle:
        if self.project_root is None:
            return ContextBundle()

        repo_map = build_repo_map(self.project_root)
        agents_context = load_agents_context(self.project_root)
        candidates = retrieve_relevant_files(
            user_input,
            repo_map,
            max_results=self.max_retrieval_results,
        )
        context_text, budget_metadata = apply_context_budget(
            agents_text=format_agents_context(agents_context),
            repo_map_text=format_repo_map(repo_map),
            relevant_files_text=format_retrieval_candidates(candidates),
            budget=self.budget,
        )

        return ContextBundle(
            text=context_text,
            metadata={
                "budget": budget_metadata,
                "max_retrieval_results": self.max_retrieval_results,
            },
        )

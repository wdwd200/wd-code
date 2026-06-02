from dataclasses import dataclass
from pathlib import Path

from wdcode.context.agents import format_agents_context, load_agents_context
from wdcode.context.repo_map import build_repo_map, format_repo_map
from wdcode.context.retrieval import format_retrieval_candidates, retrieve_relevant_files


@dataclass(frozen=True)
class ContextBundle:
    text: str = ""


class ContextProvider:
    def __init__(self, project_root=None, *, max_retrieval_results=8):
        self.project_root = Path(project_root).resolve() if project_root is not None else None
        self.max_retrieval_results = max_retrieval_results

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

        return ContextBundle(
            text="\n\n".join(
                [
                    "# Project Context",
                    "## AGENTS Instructions",
                    format_agents_context(agents_context),
                    "## Repo Map",
                    format_repo_map(repo_map),
                    format_retrieval_candidates(candidates),
                ]
            )
        )

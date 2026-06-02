import re
from dataclasses import dataclass
from pathlib import PurePosixPath


TEST_QUERY_TERMS = {"test", "tests", "pytest", "testing", "测试"}
DOC_QUERY_TERMS = {"doc", "docs", "document", "documentation", "readme", "文档"}
TOOL_QUERY_TERMS = {"tool", "tools", "gateway", "registry", "guard"}
AGENT_QUERY_TERMS = {"agent", "loop", "conversation"}
CONTEXT_QUERY_TERMS = {"context", "repo", "retrieval", "agents"}
SPECIAL_QUERY_TERMS = (
    TEST_QUERY_TERMS
    | DOC_QUERY_TERMS
    | TOOL_QUERY_TERMS
    | AGENT_QUERY_TERMS
    | CONTEXT_QUERY_TERMS
)


@dataclass(frozen=True)
class RetrievalCandidate:
    path: str
    score: int
    reason: str


def retrieve_relevant_files(
    user_input: str,
    repo_map,
    *,
    max_results: int = 8,
) -> tuple[RetrievalCandidate, ...]:
    if max_results <= 0:
        raise ValueError("max_results must be greater than zero.")

    query_terms = _query_terms(user_input)
    if not query_terms:
        return ()

    candidates = []
    for entry in repo_map.entries:
        score, reasons = _score_entry(entry, query_terms)
        if score > 0:
            candidates.append(
                RetrievalCandidate(
                    path=entry.path,
                    score=score,
                    reason="; ".join(reasons),
                )
            )

    return tuple(
        sorted(candidates, key=lambda candidate: (-candidate.score, candidate.path))[:max_results]
    )


def format_retrieval_candidates(candidates: tuple[RetrievalCandidate, ...]) -> str:
    lines = ["# Relevant Files", ""]
    if not candidates:
        lines.append("No relevant files selected.")
        return "\n".join(lines)

    for candidate in candidates:
        lines.append(f"- {candidate.path} (score: {candidate.score}) {candidate.reason}")
    return "\n".join(lines)


def _score_entry(entry, query_terms):
    path = entry.path.lower()
    filename = PurePosixPath(path).name
    summary = (entry.summary or "").lower()
    reasons = []
    score = 0

    for term in sorted(query_terms):
        if term in path:
            score += 5
            reasons.append(f"path matched: {term}")
        if term in filename:
            score += 4
            reasons.append(f"filename matched: {term}")
        if term in summary:
            score += 2
            reasons.append(f"summary matched: {term}")

    if query_terms & TEST_QUERY_TERMS and entry.is_test:
        score += 3
        reasons.append("test-related query")
    if query_terms & DOC_QUERY_TERMS and entry.is_doc:
        score += 3
        reasons.append("doc-related query")

    score += _score_path_terms(path, query_terms & TOOL_QUERY_TERMS, "tool-related path", reasons)
    score += _score_path_terms(path, query_terms & AGENT_QUERY_TERMS, "agent-related path", reasons)

    if query_terms & CONTEXT_QUERY_TERMS and "/context/" in f"/{path}":
        score += 3
        reasons.append("context-related query")

    return score, reasons


def _score_path_terms(path, terms, reason_prefix, reasons):
    score = 0
    for term in sorted(terms):
        if term in path:
            score += 3
            reasons.append(f"{reason_prefix}: {term}")
    return score


def _query_terms(user_input: str) -> set[str]:
    normalized = user_input.lower().replace("_", " ")
    terms = set(re.findall(r"[a-z0-9]+|[\u4e00-\u9fff]+", normalized))
    terms.update(term for term in user_input.lower().split() if term)
    terms.update(term for term in SPECIAL_QUERY_TERMS if term in normalized)
    return terms

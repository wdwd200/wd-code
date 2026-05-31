from dataclasses import dataclass


READ_ONLY_TOOLS = {"list_files", "read_file", "search_files"}
MUTATING_TOOLS = {"write_file", "edit_file", "run_command"}
APPROVAL_MODES = {"auto", "dry_run", "require_approval"}


@dataclass(frozen=True)
class ApprovalDecision:
    allowed: bool
    reason: str
    dry_run: bool = False


def check_approval(tool_name: str, mode: str = "auto") -> ApprovalDecision:
    if mode not in APPROVAL_MODES:
        return ApprovalDecision(False, f"Unknown approval mode: {mode}")

    if mode == "auto":
        return ApprovalDecision(True, "Allowed.")

    if tool_name in READ_ONLY_TOOLS:
        return ApprovalDecision(True, "Allowed.")

    if mode == "dry_run" and tool_name in MUTATING_TOOLS:
        return ApprovalDecision(
            False,
            f"Dry-run: would execute {tool_name}, but no changes were made.",
            dry_run=True,
        )

    if mode == "require_approval" and tool_name in MUTATING_TOOLS:
        return ApprovalDecision(
            False,
            f"Approval required before executing {tool_name}.",
        )

    return ApprovalDecision(True, "Allowed.")

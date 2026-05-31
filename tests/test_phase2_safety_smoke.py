from wdcode.security.approval import check_approval
from wdcode.security.rollback import capture_git_diff, rollback_git_diff
from wdcode.tools.result import ToolResult
from wdcode.trace import TraceWriter
from wdcode.validation import run_validation


def test_phase2_safety_modules_are_importable():
    assert TraceWriter is not None
    assert check_approval is not None
    assert capture_git_diff is not None
    assert rollback_git_diff is not None
    assert run_validation is not None
    assert ToolResult.success({"ok": True}).ok is True

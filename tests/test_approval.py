from wdcode.security.approval import check_approval


def test_approval_auto_allows_existing_tool_types():
    assert check_approval("list_files", "auto").allowed is True
    assert check_approval("write_file", "auto").allowed is True
    assert check_approval("run_command", "auto").allowed is True


def test_approval_dry_run_allows_read_only_tools():
    for tool_name in ("list_files", "read_file", "search_files"):
        decision = check_approval(tool_name, "dry_run")

        assert decision.allowed is True
        assert decision.dry_run is False


def test_approval_dry_run_blocks_mutating_tools():
    for tool_name in ("write_file", "edit_file", "run_command"):
        decision = check_approval(tool_name, "dry_run")

        assert decision.allowed is False
        assert decision.dry_run is True
        assert tool_name in decision.reason


def test_approval_require_approval_blocks_mutating_tools():
    decision = check_approval("write_file", "require_approval")

    assert decision.allowed is False
    assert decision.dry_run is False
    assert "Approval required" in decision.reason


def test_approval_unknown_mode_is_rejected():
    decision = check_approval("list_files", "unknown")

    assert decision.allowed is False
    assert "Unknown approval mode" in decision.reason

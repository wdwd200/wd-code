from wdcode.tools.result import ToolResult


def test_tool_result_success_to_dict():
    result = ToolResult.success({"value": 1}, source="test")

    assert result.to_dict() == {
        "ok": True,
        "data": {"value": 1},
        "error": None,
        "metadata": {"source": "test"},
    }


def test_tool_result_failure_to_dict():
    result = ToolResult.failure("failed")

    assert result.to_dict() == {
        "ok": False,
        "data": None,
        "error": "failed",
        "metadata": {},
    }

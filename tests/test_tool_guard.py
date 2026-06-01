import json
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory

from wdcode.security.tool_guard import prepare_tool_request
from wdcode.tools import create_default_registry


@contextmanager
def project_temp_dir():
    project_root = Path(__file__).resolve().parents[1]
    temp_root = project_root / "test_tmp"
    temp_root.mkdir(exist_ok=True)
    with TemporaryDirectory(dir=temp_root) as temp_dir:
        yield project_root, Path(temp_dir)
    try:
        temp_root.rmdir()
    except OSError:
        pass


def make_tool_call(name, arguments, call_id="call_1"):
    return {
        "id": call_id,
        "type": "function",
        "function": {
            "name": name,
            "arguments": arguments if isinstance(arguments, str) else json.dumps(arguments),
        },
    }


def test_tool_guard_rejects_invalid_tool_call_shape():
    project_root = Path(__file__).resolve().parents[1]
    registry = create_default_registry(project_root)

    request = prepare_tool_request({}, registry, project_root, approval_mode="auto")

    assert request.allowed is False
    assert request.stage == "validation"
    assert request.tool_name == ""


def test_tool_guard_rejects_invalid_arguments_json():
    project_root = Path(__file__).resolve().parents[1]
    registry = create_default_registry(project_root)

    request = prepare_tool_request(
        make_tool_call("list_files", "{bad json"),
        registry,
        project_root,
        approval_mode="auto",
    )

    assert request.allowed is False
    assert request.stage == "parse"
    assert request.tool_name == "list_files"
    assert "Invalid tool arguments" in request.reason


def test_tool_guard_rejects_unknown_tool_at_lookup_stage():
    project_root = Path(__file__).resolve().parents[1]
    registry = create_default_registry(project_root)

    request = prepare_tool_request(
        make_tool_call("missing_tool", {}),
        registry,
        project_root,
        approval_mode="auto",
    )

    assert request.allowed is False
    assert request.stage == "lookup"
    assert request.tool_name == "missing_tool"


def test_tool_guard_prepares_normalized_read_request():
    project_root = Path(__file__).resolve().parents[1]
    registry = create_default_registry(project_root)

    request = prepare_tool_request(
        make_tool_call("list_files", {"path": "tests"}),
        registry,
        project_root,
        approval_mode="auto",
    )

    assert request.allowed is True
    assert request.stage == "execution"
    assert request.tool_name == "list_files"
    assert request.arguments == {"path": "tests"}
    assert request.tool is registry.get("list_files")


def test_tool_guard_rejects_sensitive_path_at_policy_stage():
    project_root = Path(__file__).resolve().parents[1]
    registry = create_default_registry(project_root)

    request = prepare_tool_request(
        make_tool_call("read_file", {"path": "model_config.json"}),
        registry,
        project_root,
        approval_mode="auto",
    )

    assert request.allowed is False
    assert request.stage == "policy"
    assert request.tool_name == "read_file"


def test_tool_guard_dry_run_blocks_write_after_policy_checks():
    with project_temp_dir() as (project_root, temp_dir):
        registry = create_default_registry(project_root)
        target = temp_dir / "created.txt"

        request = prepare_tool_request(
            make_tool_call(
                "write_file",
                {
                    "path": target.relative_to(project_root).as_posix(),
                    "content": "do not write",
                },
            ),
            registry,
            project_root,
            approval_mode="dry_run",
        )

        assert request.allowed is False
        assert request.stage == "approval"
        assert request.tool_name == "write_file"
        assert request.dry_run is True
        assert Path(request.arguments["path"]).as_posix() == target.relative_to(project_root).as_posix()
        assert not target.exists()

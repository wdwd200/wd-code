from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from wdcode.validation.discovery import (
    CLI_ASSISTANT_HELP_COMMAND,
    PACKAGE_CLI_HELP_COMMAND,
    PYTEST_COMMAND,
    discover_validation_plan,
)


@pytest.fixture
def tmp_path():
    project_root = Path(__file__).resolve().parents[1]
    temp_root = project_root / "test_tmp"
    temp_root.mkdir(exist_ok=True)
    with TemporaryDirectory(dir=temp_root) as temp_dir:
        yield Path(temp_dir)
    try:
        temp_root.rmdir()
    except OSError:
        pass


def test_validation_discovery_uses_explicit_commands_first(tmp_path):
    plan = discover_validation_plan(
        tmp_path,
        explicit_commands=[
            "python -m pytest",
            "python -m pytest",
            "pytest tests",
            "",
        ],
    )

    assert plan.source == "explicit"
    assert plan.commands == ["python -m pytest", "pytest tests"]
    assert plan.metadata["root_exists"] is True


def test_validation_discovery_discovers_tests_and_cli_help_commands(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "src" / "wdcode" / "cli").mkdir(parents=True)
    (tmp_path / "src" / "cli_assistant.py").write_text("", encoding="utf-8")
    (tmp_path / "src" / "wdcode" / "cli" / "main.py").write_text("", encoding="utf-8")

    plan = discover_validation_plan(tmp_path)

    assert plan.source == "discovered"
    assert plan.commands == [
        PYTEST_COMMAND,
        CLI_ASSISTANT_HELP_COMMAND,
        PACKAGE_CLI_HELP_COMMAND,
    ]
    assert plan.metadata == {
        "root_exists": True,
        "root_is_dir": True,
        "tests_dir_exists": True,
        "cli_assistant_exists": True,
        "cli_main_exists": True,
    }


def test_validation_discovery_discovers_package_cli_without_tests(tmp_path):
    (tmp_path / "src" / "wdcode" / "cli").mkdir(parents=True)
    (tmp_path / "src" / "wdcode" / "cli" / "main.py").write_text("", encoding="utf-8")

    plan = discover_validation_plan(tmp_path)

    assert plan.source == "discovered"
    assert plan.commands == [PACKAGE_CLI_HELP_COMMAND]
    assert plan.metadata["tests_dir_exists"] is False


def test_validation_discovery_missing_root_returns_default_plan(tmp_path):
    missing_root = tmp_path / "missing"

    plan = discover_validation_plan(missing_root)

    assert plan.source == "default"
    assert plan.commands == [PYTEST_COMMAND]
    assert plan.metadata["root_exists"] is False
    assert plan.metadata["root_is_dir"] is False


def test_validation_discovery_empty_project_falls_back_to_pytest(tmp_path):
    plan = discover_validation_plan(tmp_path)

    assert plan.source == "default"
    assert plan.commands == [PYTEST_COMMAND]
    assert plan.metadata["root_exists"] is True
    assert plan.metadata["tests_dir_exists"] is False

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


PYTEST_COMMAND = "python -m pytest"
CLI_ASSISTANT_HELP_COMMAND = "python src/cli_assistant.py --help"
PACKAGE_CLI_HELP_COMMAND = "python src/wdcode/cli/main.py --help"


@dataclass(frozen=True)
class ValidationPlan:
    commands: list[str]
    source: str
    project_root: str
    metadata: dict[str, Any] = field(default_factory=dict)


def discover_validation_plan(
    project_root: str | Path,
    *,
    explicit_commands: list[str] | None = None,
) -> ValidationPlan:
    root = Path(project_root).resolve()
    metadata = _build_metadata(root)

    explicit = _dedupe_commands(explicit_commands or [])
    if explicit:
        return ValidationPlan(
            commands=explicit,
            source="explicit",
            project_root=str(root),
            metadata=metadata,
        )

    commands: list[str] = []
    if metadata["root_exists"] and metadata["root_is_dir"]:
        if metadata["tests_dir_exists"]:
            commands.append(PYTEST_COMMAND)
        if metadata["cli_assistant_exists"]:
            commands.append(CLI_ASSISTANT_HELP_COMMAND)
        if metadata["cli_main_exists"]:
            commands.append(PACKAGE_CLI_HELP_COMMAND)

    commands = _dedupe_commands(commands)
    if commands:
        return ValidationPlan(
            commands=commands,
            source="discovered",
            project_root=str(root),
            metadata=metadata,
        )

    return ValidationPlan(
        commands=[PYTEST_COMMAND],
        source="default",
        project_root=str(root),
        metadata=metadata,
    )


def _build_metadata(root: Path) -> dict[str, Any]:
    root_exists = root.exists()
    root_is_dir = root.is_dir() if root_exists else False
    tests_dir = root / "tests"
    cli_assistant = root / "src" / "cli_assistant.py"
    cli_main = root / "src" / "wdcode" / "cli" / "main.py"
    return {
        "root_exists": root_exists,
        "root_is_dir": root_is_dir,
        "tests_dir_exists": tests_dir.is_dir() if root_is_dir else False,
        "cli_assistant_exists": cli_assistant.is_file() if root_is_dir else False,
        "cli_main_exists": cli_main.is_file() if root_is_dir else False,
    }


def _dedupe_commands(commands: list[str]) -> list[str]:
    deduped = []
    seen = set()
    for raw_command in commands:
        if not isinstance(raw_command, str):
            continue
        command = raw_command.strip()
        if not command or command in seen:
            continue
        deduped.append(command)
        seen.add(command)
    return deduped

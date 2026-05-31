from dataclasses import dataclass
from pathlib import Path
import shlex


PYTHON_COMMANDS = {"python", "python.exe", "py", "py.exe"}
BLOCKED_COMMANDS = {"rm", "sudo", "curl", "wget", "chmod", "chown", "mkfs", "dd", "ssh", "scp"}
SHELL_TOKENS = {"|", ";", "&&", "||", ">", ">>", "<", "`"}
PYTEST_SAFE_FLAGS = {"-q", "-v", "-s", "--maxfail=1"}


@dataclass(frozen=True)
class CommandDecision:
    allowed: bool
    reason: str
    argv: tuple[str, ...] = ()


def check_command_allowed(command):
    if not isinstance(command, str) or not command.strip():
        return deny("Command must be a non-empty string.")
    if contains_shell_syntax(command):
        return deny("Shell operators are not allowed.")

    try:
        argv = tuple(shlex.split(command))
    except ValueError as exc:
        return deny(f"Command could not be parsed: {exc}")

    if not argv:
        return deny("Command must not be empty.")
    if is_blocked_command(argv):
        return deny("Command is blocked by policy.")
    if is_allowed_pytest(argv) or is_allowed_compileall(argv):
        return CommandDecision(True, "Allowed by command policy.", argv)

    return deny("Command is not in the allowlist.")


def deny(reason):
    return CommandDecision(False, reason, ())


def contains_shell_syntax(command):
    return any(token in command for token in SHELL_TOKENS)


def executable_name(argv):
    return Path(argv[0]).name.lower()


def is_python_command(argv):
    return executable_name(argv) in PYTHON_COMMANDS


def is_blocked_command(argv):
    first = executable_name(argv)
    lowered = [part.lower() for part in argv]
    if first in BLOCKED_COMMANDS:
        return True
    if first == "git":
        if len(lowered) >= 2 and lowered[1] == "push":
            return True
        if len(lowered) >= 3 and lowered[1] == "reset" and "--hard" in lowered[2:]:
            return True
        if len(lowered) >= 3 and lowered[1] == "clean" and any(flag in {"-fd", "-fdx", "-xdf"} for flag in lowered[2:]):
            return True
    return False


def is_allowed_pytest(argv):
    if executable_name(argv) == "pytest":
        return all(is_safe_pytest_arg(arg) for arg in argv[1:])
    if is_python_command(argv) and len(argv) >= 3 and argv[1:3] == ("-m", "pytest"):
        return all(is_safe_pytest_arg(arg) for arg in argv[3:])
    return False


def is_safe_pytest_arg(arg):
    normalized = arg.replace("\\", "/")
    return not arg or arg in PYTEST_SAFE_FLAGS or normalized == "tests" or normalized.startswith("tests/")


def is_allowed_compileall(argv):
    if not (is_python_command(argv) and len(argv) == 4 and argv[1:3] == ("-m", "compileall")):
        return False
    return argv[3].replace("\\", "/") in {"src", "tests"}

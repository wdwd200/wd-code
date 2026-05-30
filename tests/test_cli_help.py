import os
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"


def run_help(script_path):
    env = os.environ.copy()
    env["PYTHONPATH"] = str(SRC_DIR)
    return subprocess.run(
        [sys.executable, str(script_path), "--help"],
        cwd=PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )


def test_compat_cli_help_does_not_need_api_key():
    result = run_help(SRC_DIR / "cli_assistant.py")

    assert result.returncode == 0
    assert "usage:" in result.stdout


def test_package_cli_help_does_not_need_api_key():
    result = run_help(SRC_DIR / "wdcode" / "cli" / "main.py")

    assert result.returncode == 0
    assert "usage:" in result.stdout

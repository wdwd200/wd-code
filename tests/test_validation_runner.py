import json
import subprocess
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory

from wdcode.trace import TraceWriter
from wdcode.validation import run_validation


class CompletedProcessStub:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


@contextmanager
def local_trace_path():
    temp_root = Path(__file__).resolve().parents[1] / ".test-tmp"
    temp_root.mkdir(exist_ok=True)
    with TemporaryDirectory(dir=temp_root) as temp_dir:
        yield Path(temp_dir) / "validation.jsonl"
    try:
        temp_root.rmdir()
    except OSError:
        pass


def read_jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_validation_runner_defaults_to_pytest(monkeypatch):
    project_root = Path(__file__).resolve().parents[1]
    calls = []

    def fake_run(argv, **kwargs):
        calls.append((argv, kwargs))
        return CompletedProcessStub(returncode=0, stdout="passed", stderr="")

    monkeypatch.setattr("wdcode.validation.runner.subprocess.run", fake_run)

    report = run_validation(project_root)

    assert report.ok is True
    assert [call[0] for call in calls] == [["python", "-m", "pytest"]]
    assert calls[0][1]["cwd"] == str(project_root)
    assert calls[0][1]["shell"] is False
    assert report.results[0].command == "python -m pytest"
    assert report.results[0].stdout == "passed"


def test_validation_runner_allowed_command_success(monkeypatch):
    project_root = Path(__file__).resolve().parents[1]

    def fake_run(argv, **kwargs):
        return CompletedProcessStub(returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr("wdcode.validation.runner.subprocess.run", fake_run)

    report = run_validation(project_root, commands=["python -m pytest tests/test_imports.py"])

    assert report.ok is True
    assert report.results[0].ok is True
    assert report.results[0].exit_code == 0
    assert report.results[0].stdout == "ok"
    assert report.results[0].stderr == ""
    assert report.results[0].error is None


def test_validation_runner_allowed_command_failure(monkeypatch):
    project_root = Path(__file__).resolve().parents[1]

    def fake_run(argv, **kwargs):
        return CompletedProcessStub(returncode=2, stdout="partial", stderr="failed")

    monkeypatch.setattr("wdcode.validation.runner.subprocess.run", fake_run)

    report = run_validation(project_root, commands=["python -m pytest tests/test_imports.py"])

    assert report.ok is False
    assert report.results[0].ok is False
    assert report.results[0].exit_code == 2
    assert report.results[0].stdout == "partial"
    assert report.results[0].stderr == "failed"
    assert report.results[0].error is None


def test_validation_runner_rejects_dangerous_command_without_execution(monkeypatch):
    project_root = Path(__file__).resolve().parents[1]
    calls = []

    def fake_run(argv, **kwargs):
        calls.append(argv)
        return CompletedProcessStub(returncode=0)

    monkeypatch.setattr("wdcode.validation.runner.subprocess.run", fake_run)

    report = run_validation(project_root, commands=["git push"])

    assert report.ok is False
    assert calls == []
    assert report.results[0].command == "git push"
    assert report.results[0].exit_code is None
    assert report.results[0].error


def test_validation_runner_multiple_commands_any_failure_makes_report_fail(monkeypatch):
    project_root = Path(__file__).resolve().parents[1]
    return_codes = iter([0, 1])

    def fake_run(argv, **kwargs):
        code = next(return_codes)
        return CompletedProcessStub(returncode=code, stdout=f"code {code}", stderr="")

    monkeypatch.setattr("wdcode.validation.runner.subprocess.run", fake_run)

    report = run_validation(
        project_root,
        commands=[
            "python -m pytest tests/test_imports.py",
            "python -m compileall src",
        ],
    )

    assert report.ok is False
    assert [result.ok for result in report.results] == [True, False]
    assert [result.exit_code for result in report.results] == [0, 1]


def test_validation_report_to_dict_is_json_serializable(monkeypatch):
    project_root = Path(__file__).resolve().parents[1]

    def fake_run(argv, **kwargs):
        return CompletedProcessStub(returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr("wdcode.validation.runner.subprocess.run", fake_run)

    report = run_validation(project_root, commands=["python -m pytest tests/test_imports.py"])
    payload = report.to_dict()

    assert payload["ok"] is True
    assert payload["results"][0]["command"] == "python -m pytest tests/test_imports.py"
    json.dumps(payload)


def test_validation_runner_writes_trace_events(monkeypatch):
    project_root = Path(__file__).resolve().parents[1]

    def fake_run(argv, **kwargs):
        return CompletedProcessStub(returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr("wdcode.validation.runner.subprocess.run", fake_run)

    with local_trace_path() as trace_path:
        report = run_validation(
            project_root,
            commands=["python -m pytest tests/test_imports.py"],
            trace_writer=TraceWriter(trace_path),
        )
        events = read_jsonl(trace_path)

    assert report.ok is True
    assert [event["event_type"] for event in events] == [
        "validation_started",
        "validation_command_finished",
        "validation_finished",
    ]
    assert events[0]["payload"]["commands"] == ["python -m pytest tests/test_imports.py"]
    assert events[-1]["payload"]["ok"] is True


def test_validation_runner_timeout_returns_structured_failure(monkeypatch):
    project_root = Path(__file__).resolve().parents[1]

    def fake_run(argv, **kwargs):
        raise subprocess.TimeoutExpired(
            cmd=argv,
            timeout=kwargs["timeout"],
            output=b"partial output",
            stderr=b"timed out",
        )

    monkeypatch.setattr("wdcode.validation.runner.subprocess.run", fake_run)

    report = run_validation(
        project_root,
        commands=["python -m pytest tests/test_imports.py"],
        timeout=1,
    )

    assert report.ok is False
    assert report.results[0].ok is False
    assert report.results[0].exit_code is None
    assert report.results[0].stdout == "partial output"
    assert report.results[0].stderr == "timed out"
    assert "timed out" in report.results[0].error

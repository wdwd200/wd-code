import json
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from wdcode.validation.loop import (
    ValidationLoopPolicy,
    build_repair_request,
    run_validation_loop,
    validation_loop_report_to_dict,
)
from wdcode.validation.runner import ValidationCommandResult, ValidationReport


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


class TraceRecorder:
    def __init__(self):
        self.events = []

    def write_event(self, event_type, payload):
        self.events.append({"event_type": event_type, "payload": payload})


def make_report(ok, *, command="python -m pytest", stdout="", stderr="", error=None):
    return ValidationReport(
        ok=ok,
        results=[
            ValidationCommandResult(
                command=command,
                ok=ok,
                exit_code=0 if ok else 1,
                stdout=stdout,
                stderr=stderr,
                duration_ms=12,
                error=error,
            )
        ],
    )


def test_validation_loop_policy_rejects_non_positive_attempts():
    with pytest.raises(ValueError, match="max_attempts"):
        ValidationLoopPolicy(max_attempts=0)


def test_validation_loop_policy_rejects_non_positive_output_preview():
    with pytest.raises(ValueError, match="output_preview_chars"):
        ValidationLoopPolicy(output_preview_chars=0)


def test_validation_loop_passes_on_first_attempt(monkeypatch, tmp_path):
    calls = []

    def fake_run_validation(project_root, commands=None, trace_writer=None):
        calls.append({"project_root": project_root, "commands": commands})
        return make_report(True, stdout="passed")

    monkeypatch.setattr("wdcode.validation.loop.run_validation", fake_run_validation)

    report = run_validation_loop(
        project_root=tmp_path,
        commands=["python -m pytest"],
    )

    assert report.ok is True
    assert report.attempts == 1
    assert report.final_status == "passed"
    assert report.repair_requests == []
    assert calls[0]["commands"] == ["python -m pytest"]
    json.dumps(validation_loop_report_to_dict(report))


def test_validation_loop_failure_without_repair_does_not_call_callback(monkeypatch, tmp_path):
    def fake_run_validation(project_root, commands=None, trace_writer=None):
        return make_report(False, stderr="failed")

    def repair_callback(_request):
        raise AssertionError("repair callback should not run")

    monkeypatch.setattr("wdcode.validation.loop.run_validation", fake_run_validation)

    report = run_validation_loop(
        project_root=tmp_path,
        commands=["python -m pytest"],
        repair_callback=repair_callback,
    )

    assert report.ok is False
    assert report.attempts == 1
    assert report.final_status == "failed"
    assert report.repair_requests == []


def test_validation_loop_failure_with_repair_creates_repair_request(monkeypatch, tmp_path):
    def fake_run_validation(project_root, commands=None, trace_writer=None):
        return make_report(False, stderr="assertion failed")

    monkeypatch.setattr("wdcode.validation.loop.run_validation", fake_run_validation)

    report = run_validation_loop(
        project_root=tmp_path,
        commands=["python -m pytest"],
        policy=ValidationLoopPolicy(allow_repair=True),
    )

    assert report.ok is False
    assert report.final_status == "failed_after_repair"
    assert len(report.repair_requests) == 1
    assert report.repair_requests[0]["failed_commands"] == ["python -m pytest"]
    assert "# Validation Repair Request" in report.repair_requests[0]["prompt"]


def test_validation_loop_retries_after_truthy_repair_callback(monkeypatch, tmp_path):
    reports = iter([
        make_report(False, stderr="first failure"),
        make_report(True, stdout="second pass"),
    ])
    repair_requests = []

    def fake_run_validation(project_root, commands=None, trace_writer=None):
        return next(reports)

    def repair_callback(request):
        repair_requests.append(request)
        return True

    monkeypatch.setattr("wdcode.validation.loop.run_validation", fake_run_validation)

    report = run_validation_loop(
        project_root=tmp_path,
        commands=["python -m pytest"],
        policy=ValidationLoopPolicy(max_attempts=2, allow_repair=True),
        repair_callback=repair_callback,
    )

    assert report.ok is True
    assert report.attempts == 2
    assert report.final_status == "passed"
    assert len(report.validation_reports) == 2
    assert len(repair_requests) == 1


def test_validation_loop_stops_at_max_attempts_after_repair(monkeypatch, tmp_path):
    def fake_run_validation(project_root, commands=None, trace_writer=None):
        return make_report(False, stderr="still failing")

    monkeypatch.setattr("wdcode.validation.loop.run_validation", fake_run_validation)

    report = run_validation_loop(
        project_root=tmp_path,
        commands=["python -m pytest"],
        policy=ValidationLoopPolicy(max_attempts=2, allow_repair=True),
        repair_callback=lambda _request: True,
    )

    assert report.ok is False
    assert report.attempts == 2
    assert report.final_status == "failed_after_repair"
    assert len(report.validation_reports) == 2


def test_repair_request_prompt_contains_command_exit_code_and_output_preview():
    report = make_report(
        False,
        stdout="stdout line",
        stderr="stderr line",
        error="error line",
    )

    request = build_repair_request(
        validation_report=report,
        attempt=1,
        output_preview_chars=100,
    )

    assert request.failed_commands == ["python -m pytest"]
    assert "# Validation Repair Request" in request.prompt
    assert "exit_code: 1" in request.prompt
    assert "stdout line" in request.prompt
    assert "stderr line" in request.prompt
    assert "error line" in request.prompt


def test_validation_loop_truncates_long_stdout_and_stderr(monkeypatch, tmp_path):
    long_text = "x" * 200

    def fake_run_validation(project_root, commands=None, trace_writer=None):
        return make_report(False, stdout=long_text, stderr=long_text)

    monkeypatch.setattr("wdcode.validation.loop.run_validation", fake_run_validation)

    report = run_validation_loop(
        project_root=tmp_path,
        commands=["python -m pytest"],
        policy=ValidationLoopPolicy(output_preview_chars=50),
    )
    result = report.validation_reports[0]["results"][0]

    assert result["stdout_truncated"] is True
    assert result["stderr_truncated"] is True
    assert len(result["stdout"]) <= 50
    assert len(result["stderr"]) <= 50


def test_validation_loop_trace_writer_records_loop_events(monkeypatch, tmp_path):
    trace = TraceRecorder()

    def fake_run_validation(project_root, commands=None, trace_writer=None):
        return make_report(True)

    monkeypatch.setattr("wdcode.validation.loop.run_validation", fake_run_validation)

    report = run_validation_loop(
        project_root=tmp_path,
        commands=["python -m pytest"],
        trace_writer=trace,
    )

    assert report.ok is True
    assert [event["event_type"] for event in trace.events] == [
        "validation_loop_started",
        "validation_loop_attempt_finished",
        "validation_loop_finished",
    ]


def test_validation_loop_converts_unexpected_error_to_report(monkeypatch, tmp_path):
    def fake_run_validation(project_root, commands=None, trace_writer=None):
        raise RuntimeError("unexpected validation failure")

    monkeypatch.setattr("wdcode.validation.loop.run_validation", fake_run_validation)

    report = run_validation_loop(
        project_root=tmp_path,
        commands=["python -m pytest"],
    )

    assert report.ok is False
    assert report.final_status == "failed"
    assert "unexpected validation failure" in report.metadata["error"]
    json.dumps(validation_loop_report_to_dict(report))

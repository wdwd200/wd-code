import json

import pytest

from wdcode.core.failure_recovery import (
    FailureReport,
    RetryPolicy,
    build_validation_failure_event,
    call_with_retries,
    classify_exception,
    failure_report_to_dict,
    should_retry,
)


def test_retry_policy_rejects_non_positive_max_attempts():
    with pytest.raises(ValueError, match="max_attempts"):
        RetryPolicy(max_attempts=0)


@pytest.mark.parametrize(
    ("exc", "category"),
    [
        (TimeoutError("timed out"), "timeout"),
        (ConnectionError("connection failed"), "transient"),
        (PermissionError("denied"), "permission_error"),
        (ValueError("bad input"), "invalid_request"),
    ],
)
def test_classify_exception_maps_common_errors(exc, category):
    event = classify_exception(exc, component="model")

    assert event.category == category
    assert event.exception_type == type(exc).__name__
    assert "Traceback" not in event.message


def test_should_retry_allows_retryable_timeout_and_transient_errors():
    policy = RetryPolicy(max_attempts=2)

    assert should_retry(
        classify_exception(
            TimeoutError("timed out"),
            component="model",
            attempt=1,
            max_attempts=2,
        ),
        policy,
    )
    assert should_retry(
        classify_exception(
            ConnectionError("connection failed"),
            component="model",
            attempt=1,
            max_attempts=2,
        ),
        policy,
    )


def test_should_retry_rejects_invalid_request_and_permission_errors():
    policy = RetryPolicy(max_attempts=3)

    assert not should_retry(
        classify_exception(
            ValueError("bad input"),
            component="model",
            attempt=1,
            max_attempts=3,
        ),
        policy,
    )
    assert not should_retry(
        classify_exception(
            PermissionError("denied"),
            component="model",
            attempt=1,
            max_attempts=3,
        ),
        policy,
    )


def test_call_with_retries_eventually_succeeds_after_retryable_error():
    attempts = []

    def flaky():
        attempts.append("called")
        if len(attempts) == 1:
            raise TimeoutError("temporary timeout")
        return "ok"

    result = call_with_retries(flaky, component="model", policy=RetryPolicy(max_attempts=2))

    assert result.value == "ok"
    assert len(attempts) == 2
    assert result.report.final_status == "success"
    assert len(result.report.events) == 1
    assert result.report.events[0].retryable is True


def test_call_with_retries_reraises_last_exception_with_failure_report():
    attempts = []

    def always_fails():
        attempts.append("called")
        raise TimeoutError(f"timeout {len(attempts)}")

    with pytest.raises(TimeoutError) as exc_info:
        call_with_retries(always_fails, component="model", policy=RetryPolicy(max_attempts=2))

    report = exc_info.value.failure_report
    assert len(attempts) == 2
    assert report.final_status == "failed"
    assert [event.attempt for event in report.events] == [1, 2]
    assert report.events[-1].retryable is False


def test_call_with_retries_does_not_retry_non_retryable_error():
    attempts = []

    def invalid_request():
        attempts.append("called")
        raise ValueError("invalid request")

    with pytest.raises(ValueError) as exc_info:
        call_with_retries(invalid_request, component="model", policy=RetryPolicy(max_attempts=3))

    assert len(attempts) == 1
    assert exc_info.value.failure_report.events[0].category == "invalid_request"


def test_failure_report_to_dict_is_json_serializable_and_redacts_sensitive_metadata():
    event = classify_exception(
        TimeoutError("timed out"),
        component="model",
        attempt=1,
        max_attempts=2,
        metadata={"api_key": "secret-value", "stage": "model_call"},
    )
    report = FailureReport(events=[event], final_status="failed", metadata={"token": "secret-token"})

    payload = failure_report_to_dict(report)

    json.dumps(payload)
    assert payload["events"][0]["metadata"]["api_key"] == "[REDACTED]"
    assert payload["metadata"]["token"] == "[REDACTED]"
    assert "secret-value" not in json.dumps(payload)


def test_build_validation_failure_event_truncates_output_preview():
    long_output = "x" * 1200

    event = build_validation_failure_event(
        command="python -m pytest",
        returncode=1,
        output_preview=long_output,
    )

    assert event.component == "validation"
    assert event.category == "validation_error"
    assert event.retryable is False
    assert len(event.metadata["output_preview"]) == 1000

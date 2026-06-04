import json
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from wdcode.session import (
    SessionRecord,
    SessionStore,
    create_session_id,
    validate_session_id,
)


@contextmanager
def temp_session_dir():
    project_root = Path(__file__).resolve().parents[1]
    temp_root = project_root / "test_tmp"
    temp_root.mkdir(exist_ok=True)
    with TemporaryDirectory(dir=temp_root) as temp_dir:
        yield Path(temp_dir)
    try:
        temp_root.rmdir()
    except OSError:
        pass


def make_record(session_id="test-session"):
    return SessionRecord(
        session_id=session_id,
        messages=[
            {"role": "system", "content": "system"},
            {"role": "user", "content": "hello"},
        ],
        created_at="2026-06-02T10:00:00+00:00",
        updated_at="2026-06-02T10:01:00+00:00",
        metadata={"project": "wd-code"},
    )


def make_recovery_summary():
    return {
        "summary": "# Recovery Summary\n\nEarlier conversation contained 12 messages.",
        "source_message_count": 12,
        "recent_message_count": 4,
        "metadata": {"generated_by": "rule_based", "truncated": False},
    }


def make_compression_summary():
    return {
        "summary": "# Compressed Conversation History\n\nEarlier messages compressed.",
        "source_message_count": 20,
        "kept_recent_message_count": 4,
        "compressed_message_count": 16,
        "key_files": ["src/wdcode/session/compression.py"],
        "key_tool_results": [{"tool_call_id": "call_1", "content_preview": "ok"}],
        "source_range": {"start_index": 0, "end_index": 15},
        "metadata": {"method": "deterministic-rule-based"},
    }


def make_validation_metadata():
    return {
        "latest_validation_ok": True,
        "latest_validation_status": "passed",
        "latest_validation_attempts": 1,
        "latest_validation_commands": ["python -m pytest"],
        "latest_validation_report": {
            "ok": True,
            "attempts": 1,
            "validation_reports": [{"ok": True, "results": []}],
            "repair_requests": [],
            "final_status": "passed",
            "metadata": {"commands": ["python -m pytest"]},
        },
    }


def test_create_session_id_generates_valid_file_name_id():
    session_id = create_session_id()

    assert validate_session_id(session_id) == session_id
    assert "/" not in session_id
    assert "\\" not in session_id
    assert ".." not in session_id


@pytest.mark.parametrize("session_id", ["../abc", "a/b", r"a\b", "", "bad id"])
def test_validate_session_id_rejects_unsafe_values(session_id):
    with pytest.raises(ValueError):
        validate_session_id(session_id)


def test_session_store_save_writes_json_and_load_reads_record():
    with temp_session_dir() as session_dir:
        store = SessionStore(session_dir)
        record = make_record()

        store.save(record)
        loaded = store.load("test-session")
        raw_json = (session_dir / "test-session.json").read_text(encoding="utf-8")

    assert loaded == record
    assert '"version": 1' in raw_json
    assert "wd-code" in raw_json
    assert '"recovery_summary": null' in raw_json


def test_session_store_load_missing_session_returns_none():
    with temp_session_dir() as session_dir:
        store = SessionStore(session_dir)

        assert store.load("missing-session") is None


def test_session_store_exists_reports_saved_session():
    with temp_session_dir() as session_dir:
        store = SessionStore(session_dir)
        store.save(make_record("exists-session"))

        assert store.exists("exists-session") is True
        assert store.exists("missing-session") is False


def test_session_store_load_rejects_broken_json():
    with temp_session_dir() as session_dir:
        session_dir.mkdir(parents=True, exist_ok=True)
        (session_dir / "broken-session.json").write_text("{broken json", encoding="utf-8")
        store = SessionStore(session_dir)

        with pytest.raises(ValueError, match="Invalid session JSON"):
            store.load("broken-session")


def test_session_store_load_rejects_unsupported_version():
    with temp_session_dir() as session_dir:
        session_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 999,
            "session_id": "old-session",
            "created_at": "2026-06-02T10:00:00+00:00",
            "updated_at": "2026-06-02T10:01:00+00:00",
            "messages": [],
            "metadata": {},
        }
        (session_dir / "old-session.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        store = SessionStore(session_dir)

        with pytest.raises(ValueError, match="Unsupported session version"):
            store.load("old-session")


def test_session_store_save_and_load_preserves_recovery_summary():
    with temp_session_dir() as session_dir:
        store = SessionStore(session_dir)
        record = make_record("summary-session")
        record = SessionRecord(
            session_id=record.session_id,
            messages=record.messages,
            created_at=record.created_at,
            updated_at=record.updated_at,
            metadata=record.metadata,
            recovery_summary=make_recovery_summary(),
        )

        store.save(record)
        loaded = store.load("summary-session")

    assert loaded is not None
    assert loaded.recovery_summary == make_recovery_summary()


def test_session_store_save_and_load_preserves_compression_summary():
    with temp_session_dir() as session_dir:
        store = SessionStore(session_dir)
        record = make_record("compression-session")
        record = SessionRecord(
            session_id=record.session_id,
            messages=record.messages,
            created_at=record.created_at,
            updated_at=record.updated_at,
            metadata=record.metadata,
            recovery_summary=make_recovery_summary(),
            compression_summary=make_compression_summary(),
        )

        store.save(record)
        loaded = store.load("compression-session")

    assert loaded is not None
    assert loaded.metadata == {"project": "wd-code"}
    assert loaded.recovery_summary == make_recovery_summary()
    assert loaded.compression_summary == make_compression_summary()


def test_session_store_save_and_load_preserves_validation_metadata():
    with temp_session_dir() as session_dir:
        store = SessionStore(session_dir)
        record = make_record("validation-session")
        record = SessionRecord(
            session_id=record.session_id,
            messages=record.messages,
            created_at=record.created_at,
            updated_at=record.updated_at,
            metadata={
                **record.metadata,
                **make_validation_metadata(),
            },
            recovery_summary=make_recovery_summary(),
            compression_summary=make_compression_summary(),
        )

        store.save(record)
        loaded = store.load("validation-session")

    assert loaded is not None
    assert loaded.metadata["project"] == "wd-code"
    assert loaded.metadata["latest_validation_ok"] is True
    assert loaded.metadata["latest_validation_status"] == "passed"
    assert loaded.metadata["latest_validation_commands"] == ["python -m pytest"]
    assert loaded.recovery_summary == make_recovery_summary()
    assert loaded.compression_summary == make_compression_summary()


def test_session_store_loads_old_session_without_recovery_summary():
    with temp_session_dir() as session_dir:
        payload = {
            "version": 1,
            "session_id": "old-format",
            "created_at": "2026-06-02T10:00:00+00:00",
            "updated_at": "2026-06-02T10:01:00+00:00",
            "messages": [{"role": "system", "content": "system"}],
            "metadata": {},
        }
        (session_dir / "old-format.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        store = SessionStore(session_dir)

        loaded = store.load("old-format")

    assert loaded is not None
    assert loaded.recovery_summary is None
    assert loaded.compression_summary is None


def test_session_store_loads_old_session_without_metadata():
    with temp_session_dir() as session_dir:
        payload = {
            "version": 1,
            "session_id": "old-no-metadata",
            "created_at": "2026-06-02T10:00:00+00:00",
            "updated_at": "2026-06-02T10:01:00+00:00",
            "messages": [{"role": "system", "content": "system"}],
            "recovery_summary": make_recovery_summary(),
        }
        (session_dir / "old-no-metadata.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        store = SessionStore(session_dir)

        loaded = store.load("old-no-metadata")

    assert loaded is not None
    assert loaded.metadata == {}
    assert loaded.recovery_summary == make_recovery_summary()

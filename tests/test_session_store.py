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

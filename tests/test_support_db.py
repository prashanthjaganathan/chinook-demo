import hashlib
import sqlite3
from pathlib import Path

import pytest

from chinook_agent import db, support_db


@pytest.fixture(autouse=True)
def scratch_db(tmp_path, monkeypatch):
    monkeypatch.setenv("SUPPORT_DB", str(tmp_path / "support.sqlite"))
    return tmp_path / "support.sqlite"


def a_request(**overrides):
    fields = {
        "customer_id": 54,
        "invoice_line_id": 1111,
        "track_id": 1504,
        "action": "refund",
        "replacement_track_id": None,
        "amount": "0.99",
        "reason": "will not play on Android",
    }
    return {**fields, **overrides}


def test_request_is_recorded():
    row = support_db.record("key-1", **a_request())

    assert row["status"] == "open"
    assert row["amount"] == "0.99"
    assert row["created_at"]


def test_replaying_the_same_request_creates_one_row():
    support_db.record("key-1", **a_request())
    support_db.record("key-1", **a_request())

    assert len(support_db.open_requests(54)) == 1


def test_replay_with_different_arguments_is_rejected():
    support_db.record("key-1", **a_request())

    with pytest.raises(ValueError, match="different details"):
        support_db.record("key-1", **a_request(track_id=999))


def test_a_second_thread_cannot_refund_the_same_line():
    support_db.record("thread-a", **a_request())

    with pytest.raises(sqlite3.IntegrityError):
        support_db.record("thread-b", **a_request())


def test_a_settled_line_can_be_requested_again():
    support_db.record("key-1", **a_request())
    connection = support_db.connect()
    connection.execute("UPDATE refund_requests SET status = 'rejected'")
    connection.commit()
    connection.close()

    assert support_db.record("key-2", **a_request())["status"] == "open"


def test_different_lines_are_independent():
    support_db.record("key-1", **a_request())
    support_db.record("key-2", **a_request(invoice_line_id=2222, track_id=1))

    assert len(support_db.open_requests(54)) == 2


def test_request_key_is_stable_and_thread_scoped():
    assert support_db.request_key("t1", "c1") == support_db.request_key("t1", "c1")
    assert support_db.request_key("t1", "c1") != support_db.request_key("t2", "c1")
    assert support_db.request_key("t1", "c1") != support_db.request_key("t1", "c2")


def test_the_support_store_refuses_to_be_the_chinook_database(monkeypatch):
    monkeypatch.setenv("SUPPORT_DB", str(db.DB_PATH))

    with pytest.raises(ValueError, match="must differ"):
        support_db.connect()


def test_chinook_db_is_never_modified(chinook_db):
    before = hashlib.sha256(Path(chinook_db).read_bytes()).hexdigest()
    support_db.record("key-1", **a_request())

    assert hashlib.sha256(Path(chinook_db).read_bytes()).hexdigest() == before


def test_concurrent_writes_do_not_fail_with_database_locked():
    from concurrent.futures import ThreadPoolExecutor

    def write(index: int):
        return support_db.record(
            f"key-{index}", **a_request(invoice_line_id=index, track_id=index)
        )

    with ThreadPoolExecutor(max_workers=8) as pool:
        rows = list(pool.map(write, range(1, 21)))

    assert len(rows) == 20
    assert len(support_db.open_requests(54)) == 20

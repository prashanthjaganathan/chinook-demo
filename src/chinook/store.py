import hashlib
import os
import sqlite3
from pathlib import Path

from chinook import catalog

DEFAULT_PATH = Path(__file__).resolve().parents[2] / "data" / "support.sqlite"

SCHEMA = """
CREATE TABLE IF NOT EXISTS refund_requests (
    request_key TEXT PRIMARY KEY,
    customer_id INTEGER NOT NULL,
    invoice_line_id INTEGER NOT NULL,
    track_id INTEGER NOT NULL,
    action TEXT NOT NULL,
    replacement_track_id INTEGER,
    amount TEXT NOT NULL,
    reason TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE UNIQUE INDEX IF NOT EXISTS one_live_request_per_line
    ON refund_requests(invoice_line_id) WHERE status IN ('open', 'approved');
CREATE TABLE IF NOT EXISTS thread_owners (
    thread_id TEXT PRIMARY KEY,
    customer_id INTEGER NOT NULL
);
"""
MATCHED = ("customer_id", "invoice_line_id", "track_id", "action", "replacement_track_id")


def path() -> Path:
    return Path(os.environ.get("SUPPORT_DB", DEFAULT_PATH))


def connect() -> sqlite3.Connection:
    if path().resolve() == catalog.DB_PATH.resolve():
        raise ValueError("SUPPORT_DB must differ from the Chinook database")
    path().parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path(), timeout=10)
    connection.row_factory = sqlite3.Row
    # WAL plus a busy timeout so concurrent runs queue instead of failing.
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA busy_timeout=10000")
    connection.executescript(SCHEMA)
    return connection


def request_key(thread_id: str, tool_call_id: str) -> str:
    return hashlib.sha256(f"{thread_id}:{tool_call_id}".encode()).hexdigest()[:32]


def record(key: str, **fields) -> dict:
    connection = connect()
    try:
        existing = connection.execute(
            "SELECT * FROM refund_requests WHERE request_key = ?", (key,)).fetchone()
        if existing:
            if any(existing[name] != fields[name] for name in MATCHED):
                raise ValueError("this request was already made with different details")
            return dict(existing)
        connection.execute(
            """
            INSERT INTO refund_requests (request_key, customer_id, invoice_line_id, track_id,
                                         action, replacement_track_id, amount, reason)
            VALUES (:request_key, :customer_id, :invoice_line_id, :track_id,
                    :action, :replacement_track_id, :amount, :reason)
            """,
            {"request_key": key, **fields},
        )
        connection.commit()
        return dict(connection.execute(
            "SELECT * FROM refund_requests WHERE request_key = ?", (key,)).fetchone())
    finally:
        connection.close()


def open_requests(customer_id: int) -> list[dict]:
    connection = connect()
    try:
        rows = connection.execute(
            "SELECT * FROM refund_requests WHERE customer_id = ? ORDER BY created_at",
            (catalog.valid_id(customer_id, "customer_id"),))
        return [dict(row) for row in rows]
    finally:
        connection.close()


def bind_thread(thread_id: str, customer_id: int) -> int:
    """Claims a thread for a customer; the first claim wins, and the owner is returned."""
    connection = connect()
    try:
        connection.execute(
            "INSERT OR IGNORE INTO thread_owners (thread_id, customer_id) VALUES (?, ?)",
            (str(thread_id), catalog.valid_id(customer_id, "customer_id")))
        connection.commit()
        return connection.execute(
            "SELECT customer_id FROM thread_owners WHERE thread_id = ?",
            (str(thread_id),)).fetchone()["customer_id"]
    finally:
        connection.close()

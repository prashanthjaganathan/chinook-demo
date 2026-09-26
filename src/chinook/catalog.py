import sqlite3
from decimal import Decimal
from pathlib import Path

from chinook import config

DB_PATH = Path(__file__).resolve().parents[2] / "data" / "chinook.db"
SQLITE_MAX_INT = 2**63 - 1


def connect() -> sqlite3.Connection:
    connection = sqlite3.connect(f"{DB_PATH.as_uri()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def query(sql: str, params: tuple | dict) -> list[dict]:
    connection = connect()
    try:
        return [dict(row) for row in connection.execute(sql, params)]
    finally:
        connection.close()


def money(value) -> Decimal:
    return Decimal(str(value))


def with_money(rows: list[dict], field: str = "unit_price") -> list[dict]:
    for row in rows:
        row[field] = money(row[field])
    return rows


def valid_id(value, field: str) -> int:
    # isinstance accepts True, which SQLite would read as id 1.
    if type(value) is not int or not 1 <= value <= SQLITE_MAX_INT:
        raise ValueError(f"{field} must be a positive integer")
    return value


def valid_text(value, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or len(value) > config.MAX_SEARCH_TEXT:
        raise ValueError(f"{field} must be text of at most {config.MAX_SEARCH_TEXT} characters")
    return value.strip() or None


def clamped_limit(value) -> int:
    if type(value) is not int:
        raise ValueError("limit must be an integer")
    return max(1, min(value, config.MAX_SEARCH_RESULTS))

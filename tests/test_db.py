import sqlite3

import pytest

from chinook_agent import db


def test_connection_is_read_only():
    connection = db.connect()
    try:
        with pytest.raises(sqlite3.OperationalError):
            connection.execute("DELETE FROM Customer")
    finally:
        connection.close()


def test_rows_are_readable_by_column_name():
    connection = db.connect()
    try:
        row = connection.execute(
            "SELECT FirstName, Country FROM Customer WHERE CustomerId = ?", (1,)
        ).fetchone()
    finally:
        connection.close()

    assert row["FirstName"] == "Luís"
    assert row["Country"] == "Brazil"

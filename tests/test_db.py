import ast
import sqlite3
from pathlib import Path

import pytest

from chinook_agent import db

SOURCE_DIR = Path(__file__).resolve().parents[1] / "src" / "chinook_agent"
SQL_STARTS = (
    "SELECT", "INSERT", "UPDATE", "DELETE", "WITH", "CREATE",
    "DROP", "REPLACE", "WHERE", "ORDER BY", "LIMIT", "JOIN", "VALUES",
)
WRITE_STATEMENTS = (
    "DELETE FROM Customer",
    "UPDATE Track SET Name = 'x'",
    "INSERT INTO Genre (Name) VALUES ('x')",
    "CREATE TABLE scratch (a INT)",
    "DROP TABLE Album",
)


def _is_sql(text: str) -> bool:
    return text.strip().upper().startswith(SQL_STARTS)


def test_every_write_statement_is_rejected():
    connection = db.connect()
    try:
        for statement in WRITE_STATEMENTS:
            with pytest.raises(sqlite3.OperationalError):
                connection.execute(statement)
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


def test_every_sql_call_is_parameterized():
    for path in SOURCE_DIR.glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.JoinedStr):
                literal = "".join(
                    part.value for part in node.values if isinstance(part, ast.Constant)
                )
                assert not _is_sql(literal), f"f-string builds SQL in {path.name}"
            if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Mod)):
                for side in (node.left, node.right):
                    if isinstance(side, ast.Constant) and isinstance(side.value, str):
                        assert not _is_sql(side.value), f"SQL is concatenated in {path.name}"

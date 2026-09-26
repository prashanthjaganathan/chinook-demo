import ast
import importlib
import sqlite3
from decimal import Decimal
from pathlib import Path

import pytest

from chinook.foundation import config
from chinook.helpers import catalog

SOURCE = Path(__file__).resolve().parents[1] / "src" / "chinook"
SQL_STARTS = ("SELECT", "INSERT", "UPDATE", "DELETE", "WITH", "CREATE", "DROP", "WHERE", "AND ")
BAD_IDS = ("2", 2.0, 0, -1, 2**63, None, [1], True)


def test_package_imports():
    assert importlib.import_module("chinook")


def test_database_has_expected_row_counts(chinook_db):
    connection = sqlite3.connect(chinook_db)
    counts = [
        connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        for table in ("Invoice", "Track", "Customer")
    ]
    connection.close()

    assert counts == [412, 3503, 59]


def test_connection_is_read_only():
    connection = catalog.connect()
    with pytest.raises(sqlite3.OperationalError):
        connection.execute("DELETE FROM Customer")
    connection.close()


def test_every_write_statement_is_rejected():
    connection = catalog.connect()
    for statement in (
        "UPDATE Track SET Name = 'x'",
        "INSERT INTO Genre (Name) VALUES ('x')",
        "CREATE TABLE scratch (a INT)",
        "DROP TABLE Album",
    ):
        with pytest.raises(sqlite3.OperationalError):
            connection.execute(statement)
    connection.close()


def test_customer_id_must_be_a_real_int():
    for value in BAD_IDS:
        with pytest.raises(ValueError):
            catalog.valid_id(value, "customer_id")

    assert catalog.valid_id(54, "customer_id") == 54


def test_discount_outside_zero_to_one_fails_at_import():
    for value in (Decimal("-0.1"), Decimal("1"), Decimal("1.5"), 0.2, None):
        with pytest.raises(ValueError):
            config.valid_discount(value)

    assert config.COMPLETION_DISCOUNT == Decimal("0.20")


def test_text_and_limit_are_bounded():
    with pytest.raises(ValueError):
        catalog.valid_text("x" * 10_000, "track")
    assert catalog.valid_text("   ", "track") is None
    assert [catalog.clamped_limit(n) for n in (-1, 0, 10_000)] == [1, 1, config.MAX_SEARCH_RESULTS]


def test_money_is_exact():
    assert catalog.money(0.99) * 3 == Decimal("2.97")


def test_every_sql_call_is_parameterized():
    for path in SOURCE.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.JoinedStr):
                text = "".join(p.value for p in node.values if isinstance(p, ast.Constant))
                assert not text.strip().upper().startswith(SQL_STARTS), f"f-string SQL in {path.name}"
            if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Mod)):
                for side in (node.left, node.right):
                    if isinstance(side, ast.Constant) and isinstance(side.value, str):
                        assert not side.value.strip().upper().startswith(SQL_STARTS), path.name

import sqlite3
from decimal import Decimal

import pytest

from chinook_agent import db


def test_library_matches_invoice_lines(chinook_db):
    library = db.get_library(1)

    connection = sqlite3.connect(chinook_db)
    try:
        owned = {
            row[0]
            for row in connection.execute(
                "SELECT DISTINCT il.TrackId FROM Invoice i "
                "JOIN InvoiceLine il ON il.InvoiceId = i.InvoiceId "
                "WHERE i.CustomerId = ?",
                (1,),
            )
        }
    finally:
        connection.close()

    assert {row["track_id"] for row in library} == owned
    assert len(library) == len(owned)


def test_library_includes_media_type():
    media_types = {row["media_type"] for row in db.get_library(54)}

    assert media_types == {"MPEG audio file", "Protected AAC audio file"}


def test_library_prices_are_decimal():
    prices = {row["unit_price"] for row in db.get_library(1)}

    assert prices and all(isinstance(price, Decimal) for price in prices)
    assert Decimal("0.99") in prices


def test_unknown_customer_has_empty_library():
    assert db.get_library(999999) == []


def test_customer_id_must_be_a_real_int():
    for value in ("2", 2.0, 0, -1, 2**63, None, [1]):
        with pytest.raises(ValueError):
            db.get_library(value)


def test_boolean_customer_id_does_not_become_customer_one():
    with pytest.raises(ValueError):
        db.get_library(True)

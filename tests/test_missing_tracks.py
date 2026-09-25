import sqlite3
from decimal import Decimal

from chinook_agent import db

BIGGEST_ALBUM = 141
IN_STEP = 205


def _album_track_ids(connection: sqlite3.Connection, album_id: int) -> set[int]:
    return {
        row[0]
        for row in connection.execute(
            "SELECT TrackId FROM Track WHERE AlbumId = ?", (album_id,)
        )
    }


def test_missing_plus_owned_equals_whole_album(chinook_db):
    missing = {row["track_id"] for row in db.missing_tracks(48, IN_STEP)}
    owned = {row["track_id"] for row in db.get_library(48) if row["album_id"] == IN_STEP}

    connection = sqlite3.connect(chinook_db)
    try:
        whole_album = _album_track_ids(connection, IN_STEP)
    finally:
        connection.close()

    assert missing | owned == whole_album
    assert missing & owned == set()


def test_never_includes_an_owned_track():
    owned = {row["track_id"] for row in db.get_library(48)}

    for album_id in (row["album_id"] for row in db.partial_albums(48)):
        missing = {row["track_id"] for row in db.missing_tracks(48, album_id)}

        assert missing.isdisjoint(owned)


def test_fully_owned_album_has_nothing_missing(chinook_db):
    connection = sqlite3.connect(chinook_db)
    try:
        customer_id, album_id = connection.execute(
            """
            SELECT i.CustomerId, t.AlbumId
            FROM Invoice i
            JOIN InvoiceLine il ON il.InvoiceId = i.InvoiceId
            JOIN Track t ON t.TrackId = il.TrackId
            GROUP BY i.CustomerId, t.AlbumId
            HAVING COUNT(DISTINCT t.TrackId)
                   = (SELECT COUNT(*) FROM Track WHERE AlbumId = t.AlbumId)
            LIMIT 1
            """
        ).fetchone()
    finally:
        connection.close()

    assert db.missing_tracks(customer_id, album_id) == []


def test_missing_tracks_on_the_57_track_album_is_complete(chinook_db):
    missing = db.missing_tracks(44, BIGGEST_ALBUM)
    owned = [row for row in db.get_library(44) if row["album_id"] == BIGGEST_ALBUM]

    connection = sqlite3.connect(chinook_db)
    try:
        whole_album = _album_track_ids(connection, BIGGEST_ALBUM)
    finally:
        connection.close()

    assert len(whole_album) == 57
    assert len(owned) == 5
    assert len(missing) == 52


def test_customer_who_owns_nothing_is_missing_the_whole_album(chinook_db):
    missing = db.missing_tracks(999999, IN_STEP)

    connection = sqlite3.connect(chinook_db)
    try:
        whole_album = _album_track_ids(connection, IN_STEP)
    finally:
        connection.close()

    assert {row["track_id"] for row in missing} == whole_album


def test_unknown_album_has_nothing_missing():
    assert db.missing_tracks(48, 999999) == []


def test_missing_track_prices_are_decimal():
    prices = {row["unit_price"] for row in db.missing_tracks(48, IN_STEP)}

    assert prices == {Decimal("0.99")}


def test_missing_tracks_include_media_type():
    assert all(row["media_type"] for row in db.missing_tracks(48, IN_STEP))

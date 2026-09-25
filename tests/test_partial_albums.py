import sqlite3

from chinook_agent import db


def test_star_customer_has_partial_albums():
    best = db.partial_albums(48)[0]

    assert best["album"] == "In Step"
    assert best["artist"] == "Stevie Ray Vaughan & Double Trouble"
    assert (best["owned_tracks"], best["total_tracks"]) == (4, 10)


def test_counts_match_album_size(chinook_db):
    connection = sqlite3.connect(chinook_db)
    try:
        for row in db.partial_albums(48):
            total = connection.execute(
                "SELECT COUNT(*) FROM Track WHERE AlbumId = ?", (row["album_id"],)
            ).fetchone()[0]

            assert row["total_tracks"] == total
            assert 1 <= row["owned_tracks"] < total
    finally:
        connection.close()


def test_fully_owned_albums_are_not_listed(chinook_db):
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

    assert album_id not in {row["album_id"] for row in db.partial_albums(customer_id)}


def test_best_completion_ratio_comes_first():
    rows = db.partial_albums(54)
    ratios = [row["owned_tracks"] / row["total_tracks"] for row in rows]

    assert ratios == sorted(ratios, reverse=True)


def test_every_customer_has_something_to_complete():
    counts = [len(db.partial_albums(customer_id)) for customer_id in range(1, 60)]

    assert all(counts)
    assert sum(counts) == 1252


def test_unknown_customer_has_no_partial_albums():
    assert db.partial_albums(999999) == []

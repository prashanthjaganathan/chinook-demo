import sqlite3
from decimal import Decimal
from pathlib import Path

DB_PATH = Path(__file__).resolve().parents[2] / "data" / "chinook.db"
SQLITE_MAX_INT = 2**63 - 1

# Displays the tracks that the customer has purchased.
LIBRARY_SQL = """
SELECT DISTINCT
    t.TrackId AS track_id,
    t.Name AS track,
    t.AlbumId AS album_id,
    al.Title AS album,
    ar.Name AS artist,
    g.Name AS genre,
    m.Name AS media_type,
    t.UnitPrice AS unit_price
FROM Invoice i
JOIN InvoiceLine il ON il.InvoiceId = i.InvoiceId
JOIN Track t ON t.TrackId = il.TrackId
JOIN Album al ON al.AlbumId = t.AlbumId
JOIN Artist ar ON ar.ArtistId = al.ArtistId
JOIN Genre g ON g.GenreId = t.GenreId
JOIN MediaType m ON m.MediaTypeId = t.MediaTypeId
WHERE i.CustomerId = ?
ORDER BY ar.Name, al.Title, t.Name
"""

# Displays albums with number of tracks that the customer has purchased.
# This is used to recommend albums to the customer by the percentage of tracks purchased.
PARTIAL_ALBUMS_SQL = """
WITH owned AS (
    SELECT DISTINCT il.TrackId
    FROM Invoice i
    JOIN InvoiceLine il ON il.InvoiceId = i.InvoiceId
    WHERE i.CustomerId = ?
),
album_tracks AS (
    SELECT t.AlbumId, COUNT(*) AS total_tracks, COUNT(owned.TrackId) AS owned_tracks
    FROM Track t
    LEFT JOIN owned ON owned.TrackId = t.TrackId
    GROUP BY t.AlbumId
)
SELECT
    al.AlbumId AS album_id,
    al.Title AS album,
    ar.Name AS artist,
    album_tracks.owned_tracks,
    album_tracks.total_tracks
FROM album_tracks
JOIN Album al ON al.AlbumId = album_tracks.AlbumId
JOIN Artist ar ON ar.ArtistId = al.ArtistId
WHERE album_tracks.owned_tracks BETWEEN 1 AND album_tracks.total_tracks - 1
ORDER BY CAST(album_tracks.owned_tracks AS REAL) / album_tracks.total_tracks DESC,
         album_tracks.total_tracks DESC,
         al.Title
"""


def connect() -> sqlite3.Connection:
    connection = sqlite3.connect(f"{DB_PATH.as_uri()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def money(value: float) -> Decimal:
    return Decimal(str(value))


def valid_id(value: int, field: str) -> int:
    # isinstance accepts True, which SQLite would then read as id 1.
    if type(value) is not int or not 1 <= value <= SQLITE_MAX_INT:
        raise ValueError(f"{field} must be a positive integer")
    return value


def query(sql: str, params: tuple) -> list[dict]:
    connection = connect()
    try:
        return [dict(row) for row in connection.execute(sql, params)]
    finally:
        connection.close()


def get_library(customer_id: int) -> list[dict]:
    rows = query(LIBRARY_SQL, (valid_id(customer_id, "customer_id"),))
    for row in rows:
        row["unit_price"] = money(row["unit_price"])
    return rows


def partial_albums(customer_id: int) -> list[dict]:
    return query(PARTIAL_ALBUMS_SQL, (valid_id(customer_id, "customer_id"),))

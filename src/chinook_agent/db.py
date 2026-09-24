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

# Given a customer and an album, return every track on that album the customer does not already own, 
# with the format and price of each track.
MISSING_TRACKS_SQL = """
SELECT
    t.TrackId AS track_id,
    t.Name AS track,
    m.Name AS media_type,
    t.UnitPrice AS unit_price
FROM Track t
JOIN MediaType m ON m.MediaTypeId = t.MediaTypeId
WHERE NOT EXISTS (
        SELECT 1
        FROM Invoice i
        JOIN InvoiceLine il ON il.InvoiceId = i.InvoiceId
        WHERE i.CustomerId = ? AND il.TrackId = t.TrackId
      )
  AND t.AlbumId = ?
ORDER BY t.TrackId
"""

# One invoice header, only when it belongs to this customer.
INVOICE_SQL = """
SELECT
    InvoiceId AS invoice_id,
    date(InvoiceDate) AS invoice_date,
    Total AS total
FROM Invoice
WHERE CustomerId = ? AND InvoiceId = ?
"""

# Line items on one invoice, priced at what the customer actually paid.
INVOICE_LINES_SQL = """
SELECT
    il.InvoiceLineId AS invoice_line_id,
    il.TrackId AS track_id,
    t.Name AS track,
    ar.Name AS artist,
    m.Name AS media_type,
    il.UnitPrice AS unit_price,
    il.Quantity AS quantity
FROM InvoiceLine il
JOIN Track t ON t.TrackId = il.TrackId
JOIN Album al ON al.AlbumId = t.AlbumId
JOIN Artist ar ON ar.ArtistId = al.ArtistId
JOIN MediaType m ON m.MediaTypeId = t.MediaTypeId
WHERE il.InvoiceId = ?
ORDER BY il.InvoiceLineId
"""

# A foreign invoice and a nonexistent one answer the same, so ids cannot be probed.
INVOICE_NOT_FOUND = {"error": "Invoice not found on this account."}


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


def money_field(rows: list[dict], field: str = "unit_price") -> list[dict]:
    for row in rows:
        row[field] = money(row[field])
    return rows


def query(sql: str, params: tuple) -> list[dict]:
    connection = connect()
    try:
        return [dict(row) for row in connection.execute(sql, params)]
    finally:
        connection.close()


def get_library(customer_id: int) -> list[dict]:
    return money_field(query(LIBRARY_SQL, (valid_id(customer_id, "customer_id"),)))


def partial_albums(customer_id: int) -> list[dict]:
    return query(PARTIAL_ALBUMS_SQL, (valid_id(customer_id, "customer_id"),))


def missing_tracks(customer_id: int, album_id: int) -> list[dict]:
    return money_field(
        query(
            MISSING_TRACKS_SQL,
            (valid_id(customer_id, "customer_id"), valid_id(album_id, "album_id")),
        )
    )


def get_invoice(customer_id: int, invoice_id: int) -> dict:
    header = query(
        INVOICE_SQL,
        (valid_id(customer_id, "customer_id"), valid_id(invoice_id, "invoice_id")),
    )
    if not header:
        return dict(INVOICE_NOT_FOUND)

    invoice = header[0]
    invoice["total"] = money(invoice["total"])
    invoice["lines"] = money_field(query(INVOICE_LINES_SQL, (invoice_id,)))
    return invoice

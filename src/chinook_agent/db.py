import sqlite3
from decimal import Decimal
from pathlib import Path

from chinook_agent import config

DB_PATH = Path(__file__).resolve().parents[2] / "data" / "chinook.db"
SQLITE_MAX_INT = 2**63 - 1
MAX_SEARCH_TEXT = 100
MAX_SEARCH_RESULTS = 50

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

# Catalog rows matching any combination of filters, optionally hiding what a customer owns.
# instr() is a literal substring test, so % and _ in user text are not wildcards.
SEARCH_CATALOG_SQL = """
SELECT
    t.TrackId AS track_id,
    t.Name AS track,
    t.AlbumId AS album_id,
    al.Title AS album,
    ar.Name AS artist,
    g.Name AS genre,
    m.Name AS media_type,
    t.UnitPrice AS unit_price
FROM Track t
JOIN Album al ON al.AlbumId = t.AlbumId
JOIN Artist ar ON ar.ArtistId = al.ArtistId
JOIN Genre g ON g.GenreId = t.GenreId
JOIN MediaType m ON m.MediaTypeId = t.MediaTypeId
WHERE (:track IS NULL OR instr(lower(t.Name), lower(:track)) > 0)
  AND (:album IS NULL OR instr(lower(al.Title), lower(:album)) > 0)
  AND (:artist IS NULL OR instr(lower(ar.Name), lower(:artist)) > 0)  
  AND (:genre IS NULL OR instr(lower(g.Name), lower(:genre)) > 0)
  AND (:media_type IS NULL OR instr(lower(m.Name), lower(:media_type)) > 0)
  AND (:exclude_owned_for IS NULL OR NOT EXISTS (
        SELECT 1
        FROM Invoice i
        JOIN InvoiceLine il ON il.InvoiceId = i.InvoiceId
        WHERE i.CustomerId = :exclude_owned_for AND il.TrackId = t.TrackId
      ))
ORDER BY ar.Name, al.Title, t.TrackId
LIMIT :limit
"""

# Two tracks with the details a swap has to compare.
TRACK_PAIR_SQL = """
SELECT
    t.TrackId AS track_id,
    t.Name AS track,
    m.Name AS media_type,
    t.UnitPrice AS unit_price
FROM Track t
JOIN MediaType m ON m.MediaTypeId = t.MediaTypeId
WHERE t.TrackId IN (:original_id, :replacement_id)
"""

# Which of those two tracks the customer already owns.
OWNED_OF_PAIR_SQL = """
SELECT DISTINCT il.TrackId AS track_id
FROM Invoice i
JOIN InvoiceLine il ON il.InvoiceId = i.InvoiceId
WHERE i.CustomerId = :customer_id
  AND il.TrackId IN (:original_id, :replacement_id)
"""

# The customer's most recent invoice id, or nothing when they have never bought.
LATEST_INVOICE_SQL = """
SELECT InvoiceId AS invoice_id
FROM Invoice
WHERE CustomerId = ?
ORDER BY InvoiceDate DESC, InvoiceId DESC
LIMIT 1
"""

# This customer's most recent purchase of one track, with what they paid for it.
PURCHASE_SQL = """
SELECT
    il.InvoiceLineId AS invoice_line_id,
    il.InvoiceId AS invoice_id,
    il.TrackId AS track_id,
    t.Name AS track,
    m.Name AS media_type,
    il.UnitPrice AS unit_price
FROM Invoice i
JOIN InvoiceLine il ON il.InvoiceId = i.InvoiceId
JOIN Track t ON t.TrackId = il.TrackId
JOIN MediaType m ON m.MediaTypeId = t.MediaTypeId
WHERE i.CustomerId = :customer_id AND il.TrackId = :track_id
ORDER BY i.InvoiceDate DESC, il.InvoiceLineId DESC
LIMIT 1
"""

# One row when this customer exists, nothing otherwise.
CUSTOMER_EXISTS_SQL = """
SELECT 1 AS present FROM Customer WHERE CustomerId = ?
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


def money_field(rows: list[dict], field: str = "unit_price") -> list[dict]:
    for row in rows:
        row[field] = money(row[field])
    return rows


def valid_text(value: str | None, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or len(value) > MAX_SEARCH_TEXT:
        raise ValueError(f"{field} must be text of at most {MAX_SEARCH_TEXT} characters")
    return value.strip() or None


def clamped_limit(value: int) -> int:
    if type(value) is not int:
        raise ValueError("limit must be an integer")
    return max(1, min(value, MAX_SEARCH_RESULTS))


def query(sql: str, params: tuple | dict) -> list[dict]:
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


def search_catalog(
    track: str | None = None,
    album: str | None = None,
    artist: str | None = None,
    genre: str | None = None,
    media_type: str | None = None,
    exclude_owned_for: int | None = None,
    limit: int = 10,
) -> list[dict]:
    return money_field(
        query(
            SEARCH_CATALOG_SQL,
            {
                "track": valid_text(track, "track"),
                "album": valid_text(album, "album"),
                "artist": valid_text(artist, "artist"),
                "genre": valid_text(genre, "genre"),
                "media_type": valid_text(media_type, "media_type"),
                "exclude_owned_for": (
                    None
                    if exclude_owned_for is None
                    else valid_id(exclude_owned_for, "exclude_owned_for")
                ),
                "limit": clamped_limit(limit),
            },
        )
    )


def swap_problem(original: dict, replacement: dict, replacement_owned: bool) -> str | None:
    if replacement_owned:
        return "You already own that track."
    if not config.plays_anywhere(replacement["media_type"]):
        return "That replacement is protected too, so it would not play either."
    if config.media_kind(original["media_type"]) != config.media_kind(
        replacement["media_type"]
    ):
        return "A replacement has to be the same kind of item."
    if original["unit_price"] != replacement["unit_price"]:
        return "A replacement has to cost the same as the original."
    return None


def check_swap(
    customer_id: int, original_track_id: int, replacement_track_id: int
) -> str | None:
    ids = {
        "customer_id": valid_id(customer_id, "customer_id"),
        "original_id": valid_id(original_track_id, "original_track_id"),
        "replacement_id": valid_id(replacement_track_id, "replacement_track_id"),
    }
    tracks = {
        row["track_id"]: row
        for row in money_field(query(TRACK_PAIR_SQL, ids))
    }
    original = tracks.get(ids["original_id"])
    replacement = tracks.get(ids["replacement_id"])
    if original is None or replacement is None:
        return "That track is not in the catalog."

    owned = {row["track_id"] for row in query(OWNED_OF_PAIR_SQL, ids)}
    if ids["original_id"] not in owned:
        return "That purchase is not on this account."
    return swap_problem(original, replacement, ids["replacement_id"] in owned)


def latest_invoice_id(customer_id: int) -> int | None:
    rows = query(LATEST_INVOICE_SQL, (valid_id(customer_id, "customer_id"),))
    return rows[0]["invoice_id"] if rows else None


def purchase_of(customer_id: int, track_id: int) -> dict | None:
    rows = money_field(
        query(
            PURCHASE_SQL,
            {
                "customer_id": valid_id(customer_id, "customer_id"),
                "track_id": valid_id(track_id, "track_id"),
            },
        )
    )
    return rows[0] if rows else None


def customer_exists(customer_id: int) -> bool:
    return bool(query(CUSTOMER_EXISTS_SQL, (valid_id(customer_id, "customer_id"),)))

import sqlite3
from decimal import Decimal
from pathlib import Path

DB_PATH = Path(__file__).resolve().parents[2] / "data" / "chinook.db"
SQLITE_MAX_INT = 2**63 - 1

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

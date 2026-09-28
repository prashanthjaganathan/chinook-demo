import functools
import json
import sqlite3
from decimal import Decimal
from pathlib import Path

from chinook.foundation import config

DB_PATH = Path(__file__).resolve().parents[2] / "data" / "chinook.db"
SQLITE_MAX_INT = 2**63 - 1


def connect() -> sqlite3.Connection:
    connection = sqlite3.connect(f"{DB_PATH.as_uri()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def query(sql: str, params: tuple | dict) -> list[dict]:
    connection = connect()
    try:
        return [dict(row) for row in connection.execute(sql, params)]
    finally:
        connection.close()


def money(value) -> Decimal:
    return Decimal(str(value))


def with_money(rows: list[dict], field: str = "unit_price") -> list[dict]:
    for row in rows:
        row[field] = money(row[field])
    return rows


def valid_id(value, field: str) -> int:
    # isinstance accepts True, which SQLite would read as id 1.
    if type(value) is not int or not 1 <= value <= SQLITE_MAX_INT:
        raise ValueError(f"{field} must be a positive integer")
    return value


def valid_text(value, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or len(value) > config.MAX_SEARCH_TEXT:
        raise ValueError(f"{field} must be text of at most {config.MAX_SEARCH_TEXT} characters")
    return value.strip() or None


def clamped_limit(value) -> int:
    if type(value) is not int:
        raise ValueError("limit must be an integer")
    return max(1, min(value, config.MAX_SEARCH_RESULTS))


# Every track the customer owns, with album, artist, genre, and format.
LIBRARY_SQL = """
SELECT DISTINCT
    t.TrackId AS track_id, t.Name AS track, t.AlbumId AS album_id, al.Title AS album,
    ar.Name AS artist, g.Name AS genre, m.Name AS media_type, t.UnitPrice AS unit_price,
    al.ArtistId AS artist_id, t.GenreId AS genre_id
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

# The same rows as LIBRARY_SQL, for tracks bought through the agent (kept outside Chinook).
TRACKS_SQL = """
SELECT
    t.TrackId AS track_id, t.Name AS track, t.AlbumId AS album_id, al.Title AS album,
    ar.Name AS artist, g.Name AS genre, m.Name AS media_type, t.UnitPrice AS unit_price,
    al.ArtistId AS artist_id, t.GenreId AS genre_id
FROM Track t
JOIN Album al ON al.AlbumId = t.AlbumId
JOIN Artist ar ON ar.ArtistId = al.ArtistId
JOIN Genre g ON g.GenreId = t.GenreId
JOIN MediaType m ON m.MediaTypeId = t.MediaTypeId
WHERE t.TrackId IN (SELECT value FROM json_each(?))
"""

# Albums the customer started but did not finish, closest to complete first.
PARTIAL_ALBUMS_SQL = """
WITH owned AS (
    SELECT DISTINCT il.TrackId
    FROM Invoice i JOIN InvoiceLine il ON il.InvoiceId = i.InvoiceId
    WHERE i.CustomerId = ?
),
counts AS (
    SELECT t.AlbumId, COUNT(*) AS total_tracks, COUNT(owned.TrackId) AS owned_tracks
    FROM Track t LEFT JOIN owned ON owned.TrackId = t.TrackId
    GROUP BY t.AlbumId
)
SELECT al.AlbumId AS album_id, al.Title AS album, ar.Name AS artist,
       counts.owned_tracks, counts.total_tracks, al.ArtistId AS artist_id,
       (SELECT GenreId FROM Track WHERE AlbumId = al.AlbumId
        GROUP BY GenreId ORDER BY COUNT(*) DESC, GenreId LIMIT 1) AS genre_id
FROM counts
JOIN Album al ON al.AlbumId = counts.AlbumId
JOIN Artist ar ON ar.ArtistId = al.ArtistId
WHERE counts.owned_tracks BETWEEN 1 AND counts.total_tracks - 1
ORDER BY CAST(counts.owned_tracks AS REAL) / counts.total_tracks DESC,
         counts.total_tracks DESC, al.Title
"""

# Tracks on one album the customer does not own yet.
MISSING_TRACKS_SQL = """
SELECT t.TrackId AS track_id, t.Name AS track, m.Name AS media_type, t.UnitPrice AS unit_price
FROM Track t
JOIN MediaType m ON m.MediaTypeId = t.MediaTypeId
WHERE NOT EXISTS (
        SELECT 1 FROM Invoice i JOIN InvoiceLine il ON il.InvoiceId = i.InvoiceId
        WHERE i.CustomerId = ? AND il.TrackId = t.TrackId
      )
  AND t.AlbumId = ?
ORDER BY t.TrackId
"""

# Every line this customer bought, newest first.
PURCHASES_SQL = """
SELECT il.InvoiceLineId AS invoice_line_id, il.InvoiceId AS invoice_id,
       date(i.InvoiceDate) AS invoice_date, il.TrackId AS track_id, t.Name AS track,
       ar.Name AS artist, m.Name AS media_type, il.UnitPrice AS unit_price
FROM Invoice i
JOIN InvoiceLine il ON il.InvoiceId = i.InvoiceId
JOIN Track t ON t.TrackId = il.TrackId
JOIN Album al ON al.AlbumId = t.AlbumId
JOIN Artist ar ON ar.ArtistId = al.ArtistId
JOIN MediaType m ON m.MediaTypeId = t.MediaTypeId
WHERE i.CustomerId = ?
ORDER BY i.InvoiceDate DESC, il.InvoiceLineId DESC
"""

# Catalog tracks matching any filters. instr() is a literal test, so % and _ are not wildcards.
SEARCH_SQL = """
SELECT t.TrackId AS track_id, t.Name AS track, t.AlbumId AS album_id, al.Title AS album,
       ar.Name AS artist, g.Name AS genre, m.Name AS media_type, t.UnitPrice AS unit_price
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
        SELECT 1 FROM Invoice i JOIN InvoiceLine il ON il.InvoiceId = i.InvoiceId
        WHERE i.CustomerId = :exclude_owned_for AND il.TrackId = t.TrackId
      ))
ORDER BY ar.Name, al.Title, t.TrackId
LIMIT :limit
"""

# Two tracks with what a swap has to compare.
TRACK_PAIR_SQL = """
SELECT t.TrackId AS track_id, m.Name AS media_type, t.UnitPrice AS unit_price
FROM Track t JOIN MediaType m ON m.MediaTypeId = t.MediaTypeId
WHERE t.TrackId IN (:original_id, :replacement_id)
"""

# Which of those two tracks the customer owns.
OWNED_OF_PAIR_SQL = """
SELECT DISTINCT il.TrackId AS track_id
FROM Invoice i JOIN InvoiceLine il ON il.InvoiceId = i.InvoiceId
WHERE i.CustomerId = :customer_id AND il.TrackId IN (:original_id, :replacement_id)
"""

# One row when this customer exists.
CUSTOMER_EXISTS_SQL = "SELECT 1 AS present FROM Customer WHERE CustomerId = ?"

# Names to match typed text against. Track labels name the artist so duplicates can be told apart.
NAMES_SQL = {
    "artist": "SELECT ArtistId AS id, Name AS name, Name AS label FROM Artist",
    "genre": "SELECT GenreId AS id, Name AS name, Name AS label FROM Genre",
    "track": """SELECT t.TrackId AS id, t.Name AS name, t.Name || ' by ' || ar.Name AS label
                FROM Track t JOIN Album al ON al.AlbumId = t.AlbumId
                JOIN Artist ar ON ar.ArtistId = al.ArtistId""",
}

# Unowned tracks for one artist or genre (or all), most-bought in the store first.
RANKED_TRACKS_SQL = """
SELECT t.TrackId AS track_id, t.Name AS track, t.AlbumId AS album_id, al.Title AS album,
       ar.Name AS artist, g.Name AS genre, m.Name AS media_type, t.UnitPrice AS unit_price,
       (SELECT COUNT(*) FROM InvoiceLine s WHERE s.TrackId = t.TrackId) AS sales
FROM Track t
JOIN Album al ON al.AlbumId = t.AlbumId
JOIN Artist ar ON ar.ArtistId = al.ArtistId
JOIN Genre g ON g.GenreId = t.GenreId
JOIN MediaType m ON m.MediaTypeId = t.MediaTypeId
WHERE (:artist_id IS NULL OR ar.ArtistId = :artist_id)
  AND (:genre_id IS NULL OR g.GenreId = :genre_id)
  AND NOT EXISTS (SELECT 1 FROM Invoice i JOIN InvoiceLine il ON il.InvoiceId = i.InvoiceId
                  WHERE i.CustomerId = :customer_id AND il.TrackId = t.TrackId)
ORDER BY sales DESC, t.TrackId
LIMIT :limit
"""

# The store's best-selling genres, offered as choices to new customers.
TOP_GENRES_SQL = """
SELECT g.Name AS name FROM InvoiceLine il
JOIN Track t ON t.TrackId = il.TrackId JOIN Genre g ON g.GenreId = t.GenreId
GROUP BY g.GenreId ORDER BY COUNT(*) DESC, g.GenreId LIMIT 5
"""

# Every customer's phone, for matching on digits.
PHONES_SQL = "SELECT CustomerId AS customer_id, Phone AS phone FROM Customer WHERE Phone IS NOT NULL"


def get_library(customer_id: int) -> list[dict]:
    return with_money(query(LIBRARY_SQL, (valid_id(customer_id, "customer_id"),)))


def tracks(track_ids: list[int]) -> list[dict]:
    ids = [valid_id(track_id, "track_id") for track_id in track_ids]
    return with_money(query(TRACKS_SQL, (json.dumps(ids),))) if ids else []


def partial_albums(customer_id: int) -> list[dict]:
    return query(PARTIAL_ALBUMS_SQL, (valid_id(customer_id, "customer_id"),))


def missing_tracks(customer_id: int, album_id: int) -> list[dict]:
    params = (valid_id(customer_id, "customer_id"), valid_id(album_id, "album_id"))
    return with_money(query(MISSING_TRACKS_SQL, params))


@functools.lru_cache
def names(kind: str) -> tuple:
    return tuple(query(NAMES_SQL[kind], ()))


def ranked_tracks(customer_id: int, artist_id=None, genre_id=None) -> list[dict]:
    params = {"customer_id": valid_id(customer_id, "customer_id"), "artist_id": artist_id,
              "genre_id": genre_id, "limit": config.MAX_SEARCH_RESULTS}
    return with_money(query(RANKED_TRACKS_SQL, params))


def top_genres() -> list[str]:
    return [row["name"] for row in query(TOP_GENRES_SQL, ())]


def customer_purchases(customer_id: int) -> list[dict]:
    return with_money(query(PURCHASES_SQL, (valid_id(customer_id, "customer_id"),)))


def search_catalog(
    track=None, album=None, artist=None, genre=None, media_type=None,
    exclude_owned_for=None, limit=10,
) -> list[dict]:
    params = {
        "track": valid_text(track, "track"),
        "album": valid_text(album, "album"),
        "artist": valid_text(artist, "artist"),
        "genre": valid_text(genre, "genre"),
        "media_type": valid_text(media_type, "media_type"),
        "exclude_owned_for": None if exclude_owned_for is None
        else valid_id(exclude_owned_for, "exclude_owned_for"),
        "limit": clamped_limit(limit),
    }
    return with_money(query(SEARCH_SQL, params))


def swap_problem(original: dict, replacement: dict, replacement_owned: bool) -> str | None:
    if replacement_owned:
        return "You already own that track."
    if not config.plays_anywhere(replacement["media_type"]):
        return "That replacement is protected too, so it would not play either."
    if config.media_kind(original["media_type"]) != config.media_kind(replacement["media_type"]):
        return "A replacement has to be the same kind of item."
    if original["unit_price"] != replacement["unit_price"]:
        return "A replacement has to cost the same as the original."
    return None


def check_swap(customer_id: int, original_track_id: int, replacement_track_id: int) -> str | None:
    ids = {
        "customer_id": valid_id(customer_id, "customer_id"),
        "original_id": valid_id(original_track_id, "original_track_id"),
        "replacement_id": valid_id(replacement_track_id, "replacement_track_id"),
    }
    tracks = {row["track_id"]: row for row in with_money(query(TRACK_PAIR_SQL, ids))}
    original, replacement = tracks.get(ids["original_id"]), tracks.get(ids["replacement_id"])
    if original is None or replacement is None:
        return "That track is not in the catalog."
    owned = {row["track_id"] for row in query(OWNED_OF_PAIR_SQL, ids)}
    if ids["original_id"] not in owned:
        return "That purchase is not on this account."
    return swap_problem(original, replacement, ids["replacement_id"] in owned)


def digits_only(text) -> str:
    return "".join(char for char in str(text or "") if char.isdigit())


def customer_by_phone(phone: str) -> int | None:
    wanted = digits_only(phone)
    if len(wanted) < 10:
        return None
    # Stored numbers carry mixed formatting and sometimes a country code.
    matches = {
        row["customer_id"]
        for row in query(PHONES_SQL, ())
        if digits_only(row["phone"]) == wanted or digits_only(row["phone"])[-10:] == wanted[-10:]
    }
    return matches.pop() if len(matches) == 1 else None


def customer_exists(customer_id: int) -> bool:
    return bool(query(CUSTOMER_EXISTS_SQL, (valid_id(customer_id, "customer_id"),)))

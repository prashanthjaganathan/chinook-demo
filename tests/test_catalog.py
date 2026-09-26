import sqlite3
from decimal import Decimal

import pytest

from chinook import catalog, config

IN_STEP, BIGGEST_ALBUM, PROTECTED_TRACK, MP3, VIDEO_AT_99 = 205, 141, 1504, 1, 3402
MP3_ROW = {"media_type": "MPEG audio file", "unit_price": Decimal("0.99")}
VIDEO_ROW = {"media_type": "Protected MPEG-4 video file", "unit_price": Decimal("0.99")}


def sql(chinook_db, statement, params=()):
    connection = sqlite3.connect(chinook_db)
    rows = connection.execute(statement, params).fetchall()
    connection.close()
    return rows


def fully_owned_pair(chinook_db):
    return sql(chinook_db, """
        SELECT i.CustomerId, t.AlbumId FROM Invoice i
        JOIN InvoiceLine il ON il.InvoiceId = i.InvoiceId JOIN Track t ON t.TrackId = il.TrackId
        GROUP BY i.CustomerId, t.AlbumId
        HAVING COUNT(DISTINCT t.TrackId) = (SELECT COUNT(*) FROM Track WHERE AlbumId = t.AlbumId)
        LIMIT 1""")[0]


def test_library_matches_invoice_lines(chinook_db):
    owned = {r[0] for r in sql(chinook_db, "SELECT DISTINCT il.TrackId FROM Invoice i "
             "JOIN InvoiceLine il ON il.InvoiceId = i.InvoiceId WHERE i.CustomerId = 1")}
    library = catalog.get_library(1)

    assert {r["track_id"] for r in library} == owned
    assert len(library) == len(owned)


def test_library_includes_media_type_and_decimal_prices():
    library = catalog.get_library(54)

    assert {r["media_type"] for r in library} == {"MPEG audio file", "Protected AAC audio file"}
    assert all(isinstance(r["unit_price"], Decimal) for r in library)


def test_unknown_customer_has_empty_library():
    assert catalog.get_library(999999) == []


def test_star_customer_is_closest_to_in_step():
    best = catalog.partial_albums(48)[0]

    assert (best["album"], best["owned_tracks"], best["total_tracks"]) == ("In Step", 4, 10)


def test_fully_owned_albums_are_excluded(chinook_db):
    customer_id, album_id = fully_owned_pair(chinook_db)

    assert album_id not in {a["album_id"] for a in catalog.partial_albums(customer_id)}
    assert catalog.missing_tracks(customer_id, album_id) == []


def test_every_customer_has_something_to_complete():
    counts = [len(catalog.partial_albums(c)) for c in range(1, 60)]

    assert all(counts) and sum(counts) == 1252


def test_owned_plus_missing_is_the_whole_album(chinook_db):
    whole = {r[0] for r in sql(chinook_db, "SELECT TrackId FROM Track WHERE AlbumId = ?", (IN_STEP,))}
    missing = {r["track_id"] for r in catalog.missing_tracks(48, IN_STEP)}
    owned = {r["track_id"] for r in catalog.get_library(48) if r["album_id"] == IN_STEP}

    assert missing | owned == whole and not missing & owned


def test_missing_tracks_never_include_an_owned_track():
    owned = {r["track_id"] for r in catalog.get_library(48)}

    for album in catalog.partial_albums(48):
        assert {r["track_id"] for r in catalog.missing_tracks(48, album["album_id"])}.isdisjoint(owned)


def test_the_57_track_album_is_complete():
    assert len(catalog.missing_tracks(44, BIGGEST_ALBUM)) == 57 - 5


def test_artist_search_finds_all_acdc_tracks():
    assert len(catalog.search_catalog(artist="AC/DC", limit=50)) == 18


def test_injection_strings_match_nothing():
    for text in ("' OR 1=1 --", '"; DROP TABLE Track; --', "' UNION SELECT Email FROM Customer --"):
        assert catalog.search_catalog(artist=text) == []


def test_percent_and_underscore_are_literal():
    assert {r["track"] for r in catalog.search_catalog(track="%", limit=50)} == {"100% HardCore", ".07%"}
    assert catalog.search_catalog(track="_", limit=50) == []


def test_exclude_owned_removes_owned_tracks():
    offered = catalog.search_catalog(artist="AC/DC", exclude_owned_for=4, limit=50)
    owned = {r["track_id"] for r in catalog.get_library(4)}

    assert len(offered) == 14 and {r["track_id"] for r in offered}.isdisjoint(owned)


def test_search_is_bounded_and_validated():
    assert len(catalog.search_catalog()) == 10
    assert len(catalog.search_catalog(limit=10_000)) == config.MAX_SEARCH_RESULTS
    with pytest.raises(ValueError):
        catalog.search_catalog(artist="x" * 10_000)


def test_a_valid_swap_passes():
    assert catalog.check_swap(54, PROTECTED_TRACK, MP3) is None


@pytest.mark.parametrize("customer_id, original, replacement", [
    (54, PROTECTED_TRACK, PROTECTED_TRACK),   # replacement already owned
    (54, PROTECTED_TRACK, 999999),            # replacement does not exist
    (1, PROTECTED_TRACK, MP3),                # original not owned
])
def test_invalid_swaps_are_refused(customer_id, original, replacement):
    assert catalog.check_swap(customer_id, original, replacement) is not None


def test_swap_to_protected_format_is_refused():
    protected = catalog.search_catalog(media_type="Protected AAC", exclude_owned_for=54, limit=1)[0]

    assert catalog.check_swap(54, PROTECTED_TRACK, protected["track_id"]) is not None


def test_swap_rules_on_their_own():
    dearer = {**MP3_ROW, "unit_price": Decimal("1.99")}

    assert catalog.swap_problem(MP3_ROW, dict(MP3_ROW), False) is None
    assert catalog.swap_problem(MP3_ROW, dearer, False) is not None
    assert catalog.swap_problem(VIDEO_ROW, MP3_ROW, False) is not None  # the $0.99 video, track 3402


def test_no_video_format_plays_anywhere(chinook_db):
    types = {r[0] for r in sql(chinook_db, "SELECT Name FROM MediaType")}
    videos = {t for t in types if config.media_kind(t) == "video"}

    assert set(config.MEDIA_TYPES) == types
    assert videos and not any(config.plays_anywhere(t) for t in videos)


@pytest.mark.parametrize("phone", ["+1 (204) 452-6452", "204-452-6452", "2044526452"])
def test_aaron_mitchell_is_found_by_phone(phone):
    assert catalog.customer_by_phone(phone) == 32


@pytest.mark.parametrize("phone", ["+1 (999) 000-0000", "' OR 1=1 --", "", None, "123"])
def test_unknown_or_malformed_phone_finds_nobody(phone):
    assert catalog.customer_by_phone(phone) is None


def test_ranked_tracks_exclude_owned():
    owned = {t["track_id"] for t in catalog.get_library(1)}
    ranked = catalog.ranked_tracks(1)

    assert ranked and not owned & {t["track_id"] for t in ranked}


def test_ranked_tracks_order_is_sales_then_id():
    ranked = catalog.ranked_tracks(1, artist_id=90)

    assert ranked == sorted(ranked, key=lambda t: (-t["sales"], t["track_id"]))
    assert {t["artist"] for t in ranked} == {"Iron Maiden"}


def test_track_info_and_names():
    assert catalog.track_info(1) == {"artist_id": 1, "genre_id": 1}
    assert catalog.track_info(999999) is None
    assert {"id": 1, "name": "AC/DC", "label": "AC/DC"} in catalog.names("artist")
    assert len(catalog.top_genres()) == 5

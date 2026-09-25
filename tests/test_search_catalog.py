from decimal import Decimal

import pytest

from chinook_agent import db

PERCENT_TRACKS = {"100% HardCore", ".07%"}
INJECTION_STRINGS = (
    "' OR 1=1 --",
    '"; DROP TABLE Track; --',
    "' UNION SELECT Email FROM Customer --",
    "1; DELETE FROM Invoice",
)


def test_artist_search_finds_all_acdc_tracks():
    tracks = db.search_catalog(artist="AC/DC", limit=50)

    assert len(tracks) == 18
    assert {row["artist"] for row in tracks} == {"AC/DC"}


def test_sql_injection_text_matches_nothing():
    for text in INJECTION_STRINGS:
        assert db.search_catalog(artist=text) == []
        assert db.search_catalog(track=text) == []


def test_percent_sign_is_not_a_wildcard():
    # A LIKE query would return the whole catalog here; instr() returns only real matches.
    assert {row["track"] for row in db.search_catalog(track="%", limit=50)} == PERCENT_TRACKS


def test_underscore_is_not_a_single_character_wildcard():
    assert db.search_catalog(track="_", limit=50) == []


def test_percent_in_a_real_track_name_is_matched_literally():
    assert {row["track"] for row in db.search_catalog(track="0% ", limit=50)} == {"100% HardCore"}
    assert {row["track"] for row in db.search_catalog(track="7%", limit=50)} == {".07%"}


def test_apostrophes_are_searchable():
    tracks = db.search_catalog(track="Let's Get It Up", limit=50)

    assert [row["track"] for row in tracks] == ["Let's Get It Up"]


def test_accented_text_is_searchable():
    assert db.search_catalog(artist="antônio", limit=50)


def test_case_folding_is_ascii_only():
    # SQLite lower() leaves non-ASCII alone, so an upper-case accent will not match.
    assert db.search_catalog(artist="ANTÔNIO", limit=50) == []


def test_exclude_owned_removes_owned_tracks():
    owned = {row["track_id"] for row in db.get_library(4)}
    offered = db.search_catalog(artist="AC/DC", exclude_owned_for=4, limit=50)

    assert {row["track_id"] for row in offered}.isdisjoint(owned)
    assert len(offered) == 18 - 4


def test_limit_is_capped():
    assert len(db.search_catalog(limit=10_000)) == db.MAX_SEARCH_RESULTS


def test_limit_is_clamped_at_the_bottom():
    for value in (-1, 0, 1):
        assert len(db.search_catalog(limit=value)) == 1


def test_search_with_no_filters_is_bounded():
    assert len(db.search_catalog()) == 10


def test_oversized_search_text_is_rejected():
    for field in ("track", "album", "artist", "genre", "media_type"):
        with pytest.raises(ValueError):
            db.search_catalog(**{field: "x" * 10_000})


def test_non_text_search_values_are_rejected():
    for value in (1, 2.0, True, [], {}):
        with pytest.raises(ValueError):
            db.search_catalog(artist=value)


def test_non_integer_limit_is_rejected():
    for value in ("10", 2.0, None, True):
        with pytest.raises(ValueError):
            db.search_catalog(limit=value)


def test_blank_text_is_treated_as_no_filter():
    assert len(db.search_catalog(artist="   ")) == 10


def test_filters_combine():
    tracks = db.search_catalog(artist="AC/DC", album="Let There Be Rock", limit=50)

    assert {row["album"] for row in tracks} == {"Let There Be Rock"}


def test_media_type_filter_finds_protected_tracks():
    tracks = db.search_catalog(media_type="Protected AAC", limit=50)

    assert {row["media_type"] for row in tracks} == {"Protected AAC audio file"}


def test_search_prices_are_decimal():
    assert all(isinstance(row["unit_price"], Decimal) for row in db.search_catalog())

import sqlite3
from decimal import Decimal

from chinook_agent import config, db

CUSTOMER = 54
OWNED_PROTECTED = 1504
UNOWNED_MP3 = 1
VIDEO_AT_99_CENTS = 3402

MP3 = {"media_type": "MPEG audio file", "unit_price": Decimal("0.99")}
VIDEO = {"media_type": "Protected MPEG-4 video file", "unit_price": Decimal("0.99")}


def _media_types(connection: sqlite3.Connection) -> set[str]:
    return {row[0] for row in connection.execute("SELECT Name FROM MediaType")}


def test_valid_swap_passes():
    assert db.check_swap(CUSTOMER, OWNED_PROTECTED, UNOWNED_MP3) is None


def test_swap_to_self_is_refused():
    assert db.check_swap(CUSTOMER, OWNED_PROTECTED, OWNED_PROTECTED) is not None


def test_swap_to_nonexistent_track_is_refused():
    assert db.check_swap(CUSTOMER, OWNED_PROTECTED, 999999) is not None
    assert db.check_swap(CUSTOMER, 999999, UNOWNED_MP3) is not None


def test_swap_from_a_track_the_customer_does_not_own_is_refused():
    assert db.check_swap(1, OWNED_PROTECTED, UNOWNED_MP3) is not None


def test_swap_to_an_already_owned_track_is_refused():
    owned = [row["track_id"] for row in db.get_library(CUSTOMER)]

    assert db.check_swap(CUSTOMER, OWNED_PROTECTED, owned[0]) is not None


def test_swap_to_protected_format_is_refused():
    protected = db.search_catalog(
        media_type="Protected AAC", exclude_owned_for=CUSTOMER, limit=1
    )

    assert db.check_swap(CUSTOMER, OWNED_PROTECTED, protected[0]["track_id"]) is not None


def test_video_cannot_swap_to_audio_even_at_same_price():
    assert db.swap_problem(VIDEO, MP3, replacement_owned=False) is not None


def test_audio_cannot_swap_to_video():
    assert db.swap_problem(MP3, VIDEO, replacement_owned=False) is not None


def test_swap_across_prices_is_refused():
    dearer = {"media_type": "MPEG audio file", "unit_price": Decimal("1.99")}

    assert db.swap_problem(MP3, dearer, replacement_owned=False) is not None


def test_same_format_and_price_is_allowed():
    assert db.swap_problem(MP3, dict(MP3), replacement_owned=False) is None


def test_no_video_format_plays_anywhere(chinook_db):
    connection = sqlite3.connect(chinook_db)
    try:
        videos = {m for m in _media_types(connection) if config.media_kind(m) == "video"}
    finally:
        connection.close()

    assert videos == {"Protected MPEG-4 video file"}
    assert not any(config.plays_anywhere(media_type) for media_type in videos)


def test_the_99_cent_video_is_still_a_video():
    track = db.search_catalog(media_type="MPEG-4 video", limit=50)

    assert config.media_kind("Protected MPEG-4 video file") == "video"
    assert all(not config.plays_anywhere(row["media_type"]) for row in track)
    assert VIDEO_AT_99_CENTS not in {row["track_id"] for row in db.get_library(CUSTOMER)}


def test_every_media_type_is_classified(chinook_db):
    connection = sqlite3.connect(chinook_db)
    try:
        media_types = _media_types(connection)
    finally:
        connection.close()

    assert len(media_types) == 5
    assert all(config.media_kind(m) in ("audio", "video") for m in media_types)
    assert {m for m in media_types if config.plays_anywhere(m)} == {
        "MPEG audio file",
        "Purchased AAC audio file",
        "AAC audio file",
    }

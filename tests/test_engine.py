from decimal import Decimal

import pytest

from chinook.domain import engine
from chinook.foundation import config
from chinook.helpers import catalog, store

ACDC, IN_STEP, MUSO_KO = 1, 205, 263


def track(track_id, media_type, sales):
    return {"track_id": track_id, "album_id": 1, "media_type": media_type, "sales": sales}


def offered(result):
    return [o["album_id"] for o in result["offers"]]


@pytest.fixture
def new_customer(monkeypatch):
    # Every Chinook customer has purchases, so an empty library stands in for a new one.
    monkeypatch.setattr(catalog, "get_library", lambda customer_id: [])
    return 48


def test_merge_puts_new_first_dedupes_and_caps():
    current = {"device": "apple", "genres": ["Rock", "Jazz"]}
    new = {"device": None, "genres": ["Jazz", "Blues", "Latin", "Pop", "Metal"]}

    merged = engine.merge(current, new)

    assert merged["device"] == "apple"
    assert merged["genres"] == ["Jazz", "Blues", "Latin", "Pop", "Metal"]


def test_preferences_are_canonical_and_unknowns_reported():
    result = engine.recommend(48, new_preferences={"genres": ["rock", "zzzz"]})

    assert result["saved_preferences"]["genres"] == ["Rock"]
    assert result["not_recognized"] == ["zzzz"]
    assert store.get_preferences(48)["genres"] == ["Rock"]


def test_for_me_recommends_unowned_tracks_and_every_completable_album():
    result = engine.recommend(4)

    owned = {t["track_id"] for t in catalog.get_library(4)}
    assert result["status"] == "ok" and result["tracks"]
    assert not owned & {t["track_id"] for t in result["tracks"]}
    assert offered(result) == [MUSO_KO, ACDC]


def test_an_artist_request_offers_only_that_artists_albums():
    result = engine.recommend(4, artist="acdc")

    assert {t["artist"] for t in result["tracks"]} == {"AC/DC"}
    assert offered(result) == [ACDC]


def test_a_genre_request_offers_only_albums_of_that_genre():
    rock = engine.recommend(4, genre="rock")

    assert {t["genre"] for t in rock["tracks"]} == {"Rock"}
    assert offered(rock) == [ACDC]
    assert offered(engine.recommend(4, genre="world")) == [MUSO_KO]


def test_artist_and_genre_together_must_both_match():
    both = engine.recommend(4, artist="acdc", genre="rock")
    none = engine.recommend(4, artist="acdc", genre="jazz")

    assert {t["artist"] for t in both["tracks"]} == {"AC/DC"} and offered(both) == [ACDC]
    assert none["tracks"] == [] and offered(none) == []


def test_the_threshold_decides_which_albums_are_offered(monkeypatch):
    monkeypatch.setattr(config, "COMPLETION_MIN_OWNED", Decimal("0.5"))

    assert offered(engine.recommend(4)) == [MUSO_KO]


def test_unknown_and_ambiguous_names_say_which_kind(monkeypatch):
    assert engine.recommend(4, artist="qwxzv")["status"] == "not_found"
    assert engine.recommend(4, genre="qwxzv")["kind"] == "genre"

    twins = [{"id": 1, "name": "Queen", "label": "Queen"}, {"id": 2, "name": "Queen", "label": "Queen (UK)"}]
    monkeypatch.setattr(catalog, "names", lambda kind: twins)
    choice = engine.recommend(4, artist="queen")
    assert (choice["status"], choice["kind"]) == ("choose", "artist")


def test_a_picked_id_is_used_directly():
    assert offered(engine.recommend(4, artist_id=ACDC)) == [ACDC]


def test_the_same_request_gives_the_same_answer():
    assert engine.recommend(4, genre="rock") == engine.recommend(4, genre="rock")


def test_new_customer_is_asked_device_then_genres_never_twice(new_customer):
    assert engine.recommend(new_customer)["slot"] == "device"
    assert engine.recommend(new_customer)["slot"] == "genres"

    third = engine.recommend(new_customer)
    assert third["status"] == "ok" and third["tracks"]


def test_new_customer_with_stated_taste_skips_questions(new_customer):
    result = engine.recommend(new_customer, new_preferences={"device": "apple", "genres": ["jazz"]})

    assert result["status"] == "ok"
    assert {t["genre"] for t in result["tracks"]} == {"Jazz"}


def test_non_apple_listeners_get_no_protected_formats(monkeypatch):
    rows = [track(1, "Protected AAC audio file", 9), track(2, "MPEG audio file", 1)]
    monkeypatch.setattr(catalog, "ranked_tracks", lambda customer_id, **where: rows)

    assert [t["track_id"] for t in engine.ranked(48, [], playable_only=False)] == [1, 2]
    assert [t["track_id"] for t in engine.ranked(48, [], playable_only=True)] == [2]


def test_current_offer_matches_only_a_fresh_own_completable_offer():
    offer = engine.recommend(48)["offers"][0]["offer_id"]
    below = next(a for a in catalog.partial_albums(48) if a["album"] == "In Your Honor [Disc 1]")

    assert engine.current_offer(48, offer)["album_id"] == IN_STEP
    assert engine.current_offer(54, offer) is None
    assert engine.current_offer(48, f"{IN_STEP}-0000000000") is None
    assert engine.current_offer(48, engine.offer_for(48, below)["offer_id"]) is None
    assert engine.current_offer(48, "junk") is None


def test_tracks_bought_through_the_agent_shape_taste():
    offer = next(o for o in engine.recommend(48)["offers"] if o["album_id"] == IN_STEP)
    assert engine.taste(48, {}) == ([127, 84, 133], [1, 4])

    store.record_order("k1", customer_id=48, album_id=IN_STEP, offer_id=offer["offer_id"], amount="1",
                       lines=[{"track_id": t["track_id"], "track": t["track"], "artist": offer["artist"],
                               "media_type": t["media_type"], "unit_price": "0.1"} for t in offer["missing_tracks"]])

    # Stevie Ray Vaughan becomes the top artist, and Blues joins the top genres.
    assert engine.taste(48, {}) == ([133, 127, 84], [1, 6])


def test_track_lookup_matches_library_rows_and_ignores_empty():
    row = catalog.get_library(48)[0]

    assert catalog.tracks([row["track_id"]]) == [row]
    assert catalog.tracks([]) == []

from decimal import Decimal

import pytest

from chinook.domain import engine
from chinook.foundation import config
from chinook.helpers import catalog, store

IN_STEP = 205


def track(track_id, media_type, sales):
    return {"track_id": track_id, "album_id": 1, "media_type": media_type, "sales": sales}


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
    assert len(merged["genres"]) == config.MAX_PREFERENCE_ITEMS


def test_preferences_are_canonical_and_unknowns_reported():
    result = engine.recommend(48, "complete_album", new_preferences={"genres": ["rock", "zzzz"]})

    assert result["saved_preferences"]["genres"] == ["Rock"]
    assert result["not_recognized"] == ["zzzz"]
    assert store.get_preferences(48)["genres"] == ["Rock"]


def test_complete_album_offers_priced_completions():
    offers = engine.recommend(48, "complete_album")["offers"]

    assert offers[0]["album_id"] == IN_STEP
    assert offers[0]["final_price"] == offers[0]["list_price"] - offers[0]["discount"]
    assert all(isinstance(t["unit_price"], Decimal) for t in offers[0]["missing_tracks"])


def test_by_artist_resolves_typed_name_and_attaches_offer_for_started_album():
    result = engine.recommend(48, "by_artist", "foo fitghers")

    assert {t["artist"] for t in result["tracks"]} == {"Foo Fighters"}
    assert 80 in {o["album_id"] for o in result["offers"]}


def test_similar_to_track_offers_choices_then_uses_the_picked_id():
    result = engine.recommend(48, "similar_to_track", "the trooper")
    assert result["status"] == "choose"
    assert "The Trooper by Iron Maiden" in {c["label"] for c in result["choices"]}

    picked = engine.recommend(48, "similar_to_track", seed_id=result["choices"][0]["id"])
    assert picked["status"] == "ok" and picked["tracks"][0]["artist"] == "Iron Maiden"


def test_unknown_seed_is_not_found():
    assert engine.recommend(48, "by_artist", "qwxzv")["status"] == "not_found"


def test_for_me_uses_library_taste():
    result = engine.recommend(48, "for_me")

    owned = {t["track_id"] for t in catalog.get_library(48)}
    assert result["status"] == "ok" and result["tracks"]
    assert not owned & {t["track_id"] for t in result["tracks"]}


def test_new_customer_is_asked_device_then_genres_never_twice(new_customer):
    assert engine.recommend(new_customer, "for_me")["slot"] == "device"
    assert engine.recommend(new_customer, "for_me")["slot"] == "genres"

    third = engine.recommend(new_customer, "for_me")
    assert third["status"] == "ok" and third["tracks"]


def test_new_customer_with_stated_taste_skips_questions(new_customer):
    result = engine.recommend(new_customer, "for_me",
                              new_preferences={"device": "apple", "genres": ["jazz"]})

    assert result["status"] == "ok"
    assert {t["genre"] for t in result["tracks"]} == {"Jazz"}


def test_non_apple_listeners_get_no_protected_formats(monkeypatch):
    rows = [track(1, "Protected AAC audio file", 9), track(2, "MPEG audio file", 1)]
    monkeypatch.setattr(catalog, "ranked_tracks", lambda customer_id, **where: rows)

    assert [t["track_id"] for t in engine.ranked(48, [], [], playable_only=False)] == [1, 2]
    assert [t["track_id"] for t in engine.ranked(48, [], [], playable_only=True)] == [2]


def test_current_offer_matches_only_a_fresh_own_offer():
    offer = engine.recommend(48, "complete_album")["offers"][0]["offer_id"]

    assert engine.current_offer(48, offer)["album_id"] == IN_STEP
    assert engine.current_offer(54, offer) is None
    assert engine.current_offer(48, f"{IN_STEP}-0000000000") is None
    assert engine.current_offer(48, "junk") is None


def test_unknown_mode_is_rejected():
    with pytest.raises(ValueError):
        engine.recommend(48, "surprise_me")

import pytest

from chinook.helpers import catalog, resolver

ARTISTS = catalog.query("SELECT ArtistId AS id, Name AS name, Name AS label FROM Artist", ())


@pytest.mark.parametrize("typed, name", [
    ("Metallica", "Metallica"),
    ("metalica", "Metallica"),
    ("led zeplin", "Led Zeppelin"),
    ("acdc", "AC/DC"),
    ("zep", "Led Zeppelin"),
    ("the ROLLING stones", "The Rolling Stones"),
])
def test_typed_names_resolve_to_one_artist(typed, name):
    found = resolver.resolve(typed, ARTISTS)

    assert found["status"] == "found" and found["name"] == name


def test_a_shared_name_asks_the_customer_to_choose():
    rows = [{"id": 1, "name": "Yesterday", "label": "Yesterday by The Beatles"},
            {"id": 2, "name": "Yesterday", "label": "Yesterday by Leona Lewis"}]
    found = resolver.resolve("yesterday", rows)

    assert found["status"] == "choose" and {c["id"] for c in found["choices"]} == {1, 2}


def test_two_near_equal_spellings_are_ambiguous():
    rows = [{"id": 1, "name": "Jon Anderson", "label": "Jon Anderson"},
            {"id": 2, "name": "Jan Anderson", "label": "Jan Anderson"}]

    assert resolver.resolve("jin anderson", rows)["status"] == "choose"


@pytest.mark.parametrize("typed", ["zzqqxx", "", None, "' OR 1=1 --"])
def test_garbage_resolves_to_nothing(typed):
    assert resolver.resolve(typed, ARTISTS)["status"] == "not_found"


def test_normalize_folds_accents_case_and_punctuation():
    assert resolver.normalize("Antônio Carlos Jobim") == "antoniocarlosjobim"
    assert resolver.normalize("Guns N' Roses") == resolver.normalize("guns n roses")

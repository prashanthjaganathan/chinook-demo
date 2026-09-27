"""Deterministic recommendations: the same customer, mode, and seed always give the same answer."""
import hashlib
from collections import Counter

from chinook.foundation import config
from chinook.helpers import catalog, pricing, resolver, store


def offer_id(customer_id, album_id, missing, final_price) -> str:
    raw = f"{customer_id}:{album_id}:{[t['track_id'] for t in missing]}:{final_price}"
    return f"{album_id}-{hashlib.sha256(raw.encode()).hexdigest()[:10]}"


def offer_for(customer_id: int, album: dict) -> dict:
    missing = catalog.missing_tracks(customer_id, album["album_id"])
    price = pricing.completion_price([t["unit_price"] for t in missing])
    return {**album, **price, "missing_tracks": missing,
            "offer_id": offer_id(customer_id, album["album_id"], missing, price["final_price"])}


def completable(customer_id: int) -> list[dict]:
    return [a for a in catalog.partial_albums(customer_id)
            if a["owned_tracks"] >= config.COMPLETION_MIN_OWNED * a["total_tracks"]]


def current_offer(customer_id: int, offer: str) -> dict | None:
    """Re-derives the offer now; a stale, foreign, or made-up id matches nothing."""
    album_id = str(offer).split("-", 1)[0]
    album = next((a for a in completable(customer_id) if str(a["album_id"]) == album_id), None)
    fresh = offer_for(customer_id, album) if album else None
    return fresh if fresh and fresh["offer_id"] == offer else None


def merge(current: dict, new: dict) -> dict:
    merged = dict(current)
    if new.get("device"):
        merged["device"] = new["device"]
    # Newest first, no duplicates, capped.
    for key in ("genres", "artists"):
        combined = dict.fromkeys([*new.get(key, []), *current.get(key, [])])
        merged[key] = list(combined)[: config.MAX_PREFERENCE_ITEMS]
    return merged


def canonical(names: list[str], kind: str) -> tuple[list[str], list[str]]:
    known, unknown = [], []
    for name in names:
        found = resolver.resolve(name, catalog.names(kind))
        if found["status"] == "found":
            known.append(found["name"])
        else:
            unknown.append(name)
    return known, unknown


def update_preferences(customer_id: int, new: dict | None) -> tuple[dict, list[str]]:
    current = store.get_preferences(customer_id)
    if not new:
        return current, []
    genres, bad_genres = canonical(new.get("genres", []), "genre")
    artists, bad_artists = canonical(new.get("artists", []), "artist")
    merged = merge(current, {"device": new.get("device"), "genres": genres, "artists": artists})
    store.save_preferences(customer_id, merged)
    return merged, bad_genres + bad_artists


def ids(names: list[str], kind: str) -> list[int]:
    by_name = {row["name"]: row["id"] for row in catalog.names(kind)}
    return [by_name[name] for name in names if name in by_name]


def taste(customer_id: int, prefs: dict) -> tuple[list[int], list[int]]:
    library = catalog.get_library(customer_id)
    artists = [a for a, _ in Counter(t["artist_id"] for t in library).most_common(3)]
    genres = [g for g, _ in Counter(t["genre_id"] for t in library).most_common(2)]
    # Library first; saved preferences fill the gaps.
    return (list(dict.fromkeys(artists + ids(prefs.get("artists", []), "artist"))),
            list(dict.fromkeys(genres + ids(prefs.get("genres", []), "genre"))))


def next_question(prefs: dict) -> dict | None:
    asked = prefs.get("asked", [])
    if "device" not in prefs and "device" not in asked:
        return {"status": "question", "slot": "device", "question": config.ASK_DEVICE,
                "options": ["Apple", "Something else"]}
    if not prefs.get("genres") and "genres" not in asked:
        return {"status": "question", "slot": "genres", "question": config.ASK_GENRES,
                "options": catalog.top_genres()}
    return None


def ranked(customer_id: int, filters: list[tuple[int, dict]], playable_only: bool) -> list[dict]:
    # Lower tier first; within a tier, store-wide sales, then track id.
    rows = {}
    for tier, where in filters or [(0, {})]:
        for track in catalog.ranked_tracks(customer_id, **where):
            rows.setdefault(track["track_id"], {**track, "tier": tier})
    keep = [t for t in rows.values() if not playable_only or config.plays_anywhere(t["media_type"])]
    return sorted(keep, key=lambda t: (t["tier"], -t["sales"], t["track_id"]))[: config.RECOMMEND_LIMIT]


def pick(text, given_id, kind: str) -> tuple[int | None, dict | None]:
    """An id for the typed artist or genre, or a result asking the customer to choose."""
    if given_id is not None:
        return catalog.valid_id(given_id, f"{kind}_id"), None
    if not text:
        return None, None
    found = resolver.resolve(text, catalog.names(kind))
    return (found["id"], None) if found["status"] == "found" else (None, {**found, "kind": kind})


def recommend(customer_id: int, artist=None, genre=None, artist_id=None, genre_id=None,
              new_preferences=None) -> dict:
    prefs, unknown = update_preferences(customer_id, new_preferences)
    result = {"saved_preferences": prefs, "not_recognized": unknown}
    artist_id, problem = pick(artist, artist_id, "artist")
    genre_id, genre_problem = pick(genre, genre_id, "genre")
    if problem or genre_problem:
        return {**result, **(problem or genre_problem)}

    if artist_id or genre_id:
        filters = [(0, {"artist_id": artist_id, "genre_id": genre_id})]
    else:
        artists, genres = taste(customer_id, prefs)
        if not (artists or genres) and (question := next_question(prefs)):
            # Each slot is asked once, so a customer who skips it gets bestsellers next time.
            store.save_preferences(customer_id, {**prefs, "asked": [*prefs.get("asked", []), question["slot"]]})
            return {**result, **question}
        filters = [(0, {"artist_id": a}) for a in artists] + [(1, {"genre_id": g}) for g in genres]

    tracks = ranked(customer_id, filters, playable_only=prefs.get("device") == "other")
    # A completion is offered only when it fits what was asked for.
    offers = [offer_for(customer_id, a) for a in completable(customer_id)
              if artist_id in (None, a["artist_id"]) and genre_id in (None, a["genre_id"])]
    return {**result, "status": "ok", "tracks": tracks, "offers": offers}

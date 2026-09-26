"""Ranks customers who can carry both demo workflows in one conversation."""

from chinook import catalog, config

MIN_OWNED, MIN_ALBUM_TRACKS = 2, 5


def swap_options(customer_id: int, track: dict) -> list[dict]:
    candidates = catalog.search_catalog(
        artist=track["artist"], exclude_owned_for=customer_id, limit=config.MAX_SEARCH_RESULTS
    )
    return [c for c in candidates if catalog.swap_problem(track, c, replacement_owned=False) is None]


def profile(customer_id: int) -> dict | None:
    albums = [
        a for a in catalog.partial_albums(customer_id)
        if a["owned_tracks"] >= MIN_OWNED and a["total_tracks"] >= MIN_ALBUM_TRACKS
    ]
    protected = [
        t for t in catalog.get_library(customer_id) if not config.plays_anywhere(t["media_type"])
    ]
    if not albums:
        return None
    for track in protected:
        options = swap_options(customer_id, track)
        if options:
            best = albums[0]
            return {
                "customer_id": customer_id,
                "album": best["album"],
                "owned_tracks": best["owned_tracks"],
                "total_tracks": best["total_tracks"],
                "ratio": best["owned_tracks"] / best["total_tracks"],
                "swap_track_id": track["track_id"],
                "swap_options": len(options),
            }
    return None


def rank() -> list[dict]:
    found = [row for row in map(profile, range(1, 60)) if row]
    return sorted(found, key=lambda r: (r["ratio"], r["swap_options"]), reverse=True)


if __name__ == "__main__":
    for row in rank()[:8]:
        print(f"customer {row['customer_id']:>2}  {row['owned_tracks']}/{row['total_tracks']} "
              f"{row['album']!r}  swaps={row['swap_options']}")

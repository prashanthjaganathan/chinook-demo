"""Ranks the customers who can carry both demo workflows in one conversation."""

from chinook_agent import config, db

# A demo album needs enough owned tracks to show a pattern and enough missing to be an offer.
MIN_OWNED = 2
MIN_ALBUM_TRACKS = 5

# The most recent line where this customer bought this track.
INVOICE_LINE_SQL = """
SELECT i.InvoiceId AS invoice_id, il.InvoiceLineId AS invoice_line_id
FROM Invoice i
JOIN InvoiceLine il ON il.InvoiceId = i.InvoiceId
WHERE i.CustomerId = :customer_id AND il.TrackId = :track_id
ORDER BY i.InvoiceDate DESC, il.InvoiceLineId DESC
LIMIT 1
"""


def swap_options(customer_id: int, track: dict) -> list[dict]:
    candidates = db.search_catalog(
        artist=track["artist"],
        exclude_owned_for=customer_id,
        limit=db.MAX_SEARCH_RESULTS,
    )
    return [
        candidate
        for candidate in candidates
        if db.swap_problem(track, candidate, replacement_owned=False) is None
    ]


def demo_albums(customer_id: int) -> list[dict]:
    return [
        album
        for album in db.partial_albums(customer_id)
        if album["owned_tracks"] >= MIN_OWNED and album["total_tracks"] >= MIN_ALBUM_TRACKS
    ]


def profile(customer_id: int) -> dict | None:
    albums = demo_albums(customer_id)
    protected = [
        track
        for track in db.get_library(customer_id)
        if not config.plays_anywhere(track["media_type"])
    ]
    if not albums or not protected:
        return None

    for track in protected:
        options = swap_options(customer_id, track)
        if not options:
            continue
        line = db.query(
            INVOICE_LINE_SQL, {"customer_id": customer_id, "track_id": track["track_id"]}
        )[0]
        best = albums[0]
        return {
            "customer_id": customer_id,
            "partial_albums": len(albums),
            "best_album": best["album"],
            "album_id": best["album_id"],
            "owned_tracks": best["owned_tracks"],
            "total_tracks": best["total_tracks"],
            "ratio": best["owned_tracks"] / best["total_tracks"],
            "protected_owned": len(protected),
            "swap_track": track["track"],
            "swap_track_id": track["track_id"],
            "swap_options": len(options),
            **line,
        }
    return None


def rank(customer_ids: range = range(1, 60)) -> list[dict]:
    found = (profile(customer_id) for customer_id in customer_ids)
    return sorted(
        (row for row in found if row),
        key=lambda row: (row["ratio"], row["protected_owned"], row["swap_options"]),
        reverse=True,
    )


def main() -> None:
    for row in rank()[:8]:
        print(
            f"customer {row['customer_id']:>3}  "
            f"owns {row['owned_tracks']}/{row['total_tracks']} of {row['best_album']!r} "
            f"(album {row['album_id']}, {row['partial_albums']} partial albums)"
        )
        print(
            f"{'':13}refund invoice {row['invoice_id']} line {row['invoice_line_id']}: "
            f"{row['swap_track']!r} -> {row['swap_options']} valid swaps"
        )


if __name__ == "__main__":
    main()

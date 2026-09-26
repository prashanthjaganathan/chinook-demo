"""Refund decisions from a versioned checklist. The model picks the item and reason; code decides."""
import hashlib

from chinook import catalog, config, resolver


def purchase_ref(customer_id: int, invoice_line_id: int) -> str:
    digest = hashlib.sha256(f"{customer_id}:{invoice_line_id}".encode()).hexdigest()[:10]
    return f"{invoice_line_id}-{digest}"


def label(line: dict) -> str:
    return f"{line['track']} by {line['artist']}, bought {line['invoice_date']}, ${line['unit_price']}"


def closeness(text: str, value: str) -> float:
    a, b = resolver.normalize(text), resolver.normalize(value)
    return 1.0 if a and a in b else resolver.ratio(a, b)


def find(customer_id: int, track=None, artist=None, wont_play_on=None, latest=False) -> dict:
    lines = catalog.customer_purchases(customer_id)
    # With nothing to go on, show their latest order rather than guess.
    if lines and (latest or not (track or artist or wont_play_on)):
        lines = [line for line in lines if line["invoice_id"] == lines[0]["invoice_id"]]

    scored = []
    for line in lines:
        scores = [closeness(text, line[field]) for text, field in ((track, "track"), (artist, "artist")) if text]
        if all(score >= config.RESOLVE_CUTOFF for score in scores):
            # On a non-Apple device, protected files are the likely culprit, so they rank first.
            locked = not config.plays_anywhere(line["media_type"])
            boost = 0 if wont_play_on == "other" and locked else 1
            scored.append(((-sum(scores), boost), line))
    # A stable sort keeps newest-first among equals.
    top = [line for _, line in sorted(scored, key=lambda pair: pair[0])][: config.MAX_CANDIDATES]

    status = "not_found" if not top else "found" if len(top) == 1 else "choose"
    return {"status": status,
            "purchases": [{"purchase_ref": purchase_ref(customer_id, l["invoice_line_id"]), "label": label(l)}
                          for l in top],
            "reasons": config.REFUND_REASON_LABELS}


def purchase_for_ref(customer_id: int, ref: str) -> dict | None:
    """A ref only resolves for the customer it was issued to."""
    line_id = str(ref).split("-", 1)[0]
    line = next((l for l in catalog.customer_purchases(customer_id)
                 if str(l["invoice_line_id"]) == line_id), None)
    return line if line and purchase_ref(customer_id, line["invoice_line_id"]) == ref else None

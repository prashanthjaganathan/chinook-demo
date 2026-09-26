"""Turns what a customer typed into one catalog id: normalize, alias, exact, then close match."""

import difflib
import unicodedata

from chinook.foundation import config


def normalize(text) -> str:
    text = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode().lower()
    text = text.replace("&", "and").removeprefix("the ")
    return "".join(char for char in text if char.isalnum())


def ratio(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a, b).ratio()


def resolve(text, rows) -> dict:
    """rows: [{id, name, label}]. Returns found, choose, or not_found."""
    key = normalize(text)
    key = normalize(config.ALIASES.get(key, key))
    by_key = {}
    for row in rows:
        by_key.setdefault(normalize(row["name"]), []).append(row)

    if key in by_key:
        matches = by_key[key]
    else:
        close = difflib.get_close_matches(key, by_key, n=2, cutoff=config.RESOLVE_CUTOFF)
        # Two near-equal candidates are ambiguous, so the customer picks rather than us guessing.
        if len(close) == 2 and ratio(key, close[1]) >= ratio(key, close[0]) - config.RESOLVE_MARGIN:
            matches = by_key[close[0]] + by_key[close[1]]
        else:
            matches = by_key[close[0]] if close else []

    if not matches:
        return {"status": "not_found", "text": text}
    if len(matches) == 1:
        return {"status": "found", "id": matches[0]["id"], "name": matches[0]["name"]}
    return {"status": "choose", "choices": [{"id": m["id"], "label": m["label"]} for m in matches[:5]]}

from decimal import Decimal
from typing import Literal

from langchain.tools import ToolRuntime, tool
from pydantic import BaseModel

from chinook.agent import outcomes
from chinook.domain import engine, refunds
from chinook.foundation import config
from chinook.foundation.context import CustomerContext
from chinook.helpers import catalog, store


def readable(value):
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {key: readable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [readable(item) for item in value]
    return value


def customer_of(runtime: ToolRuntime[CustomerContext]) -> int | None:
    return getattr(runtime.context, "customer_id", None)


def resolve_customer(runtime: ToolRuntime[CustomerContext]) -> int | None:
    # Context is fixed when a run starts, so a login finished mid-thread lives in state.
    return customer_of(runtime) or (runtime.state or {}).get("verified_customer_id")


@tool
def search_catalog(
    runtime: ToolRuntime[CustomerContext],
    track: str | None = None,
    album: str | None = None,
    artist: str | None = None,
    genre: str | None = None,
    media_type: str | None = None,
    exclude_owned: bool = False,
    limit: int = 10,
) -> list[dict]:
    """Search the catalog by track, album, artist, genre, or file format.

    Set exclude_owned to hide what this customer already owns.
    """
    return readable(catalog.search_catalog(
        track=track, album=album, artist=artist, genre=genre, media_type=media_type,
        exclude_owned_for=customer_of(runtime) if exclude_owned else None, limit=limit,
    ))


class Preferences(BaseModel):
    device: Literal["apple", "other"] | None = None
    genres: list[str] = []
    artists: list[str] = []


@tool
def recommend_engine(
    runtime: ToolRuntime[CustomerContext],
    artist: str | None = None,
    genre: str | None = None,
    artist_id: int | None = None,
    genre_id: int | None = None,
    new_preferences: Preferences | None = None,
) -> dict:
    """Recommend tracks the customer doesn't own, plus album completions that fit the request.

    Pass artist and/or genre exactly as the customer wrote them; leave both empty for personal picks.
    If the result has choices, call again with the chosen id as artist_id or genre_id (see its kind).
    Pass any taste they state in new_preferences.
    """
    customer_id = customer_of(runtime)
    if customer_id is None:
        return {"error": config.NO_IDENTITY}
    prefs = new_preferences.model_dump(exclude_none=True) if new_preferences else None
    return readable(engine.recommend(customer_id, artist, genre, artist_id, genre_id, prefs))


@tool
def buy_completion(runtime: ToolRuntime[CustomerContext], offer_id: str) -> dict:
    """Buy the missing tracks of an album, using an offer_id from recommend_engine.

    Only call it after the customer has said yes to this offer.
    """
    customer_id = customer_of(runtime)
    if customer_id is None:
        return {"error": config.NO_IDENTITY}
    offer = engine.current_offer(customer_id, offer_id)
    if offer is None:
        return {"error": config.OFFER_CHANGED}
    thread_id = (runtime.config or {}).get("configurable", {}).get("thread_id", "")
    order = store.record_order(
        store.request_key(str(thread_id), str(runtime.tool_call_id)),
        customer_id=customer_id, album_id=offer["album_id"], offer_id=offer_id,
        amount=str(offer["final_price"]))
    return {"status": "confirmed", "album": offer["album"],
            "tracks": len(offer["missing_tracks"]), "amount": order["amount"]}


RefundReason = Literal["wont_play", "bought_by_mistake", "didnt_like_it", "other", "not_given"]
Device = Literal["apple", "other"]


@tool
def find_purchases(
    runtime: ToolRuntime[CustomerContext],
    track: str | None = None,
    artist: str | None = None,
    wont_play_on: Device | None = None,
    latest: bool = False,
) -> dict:
    """Find which of this customer's purchases they mean, from whatever they said about it.

    Returns candidates, each with a purchase_ref, and the reason options to ask about.
    """
    customer_id = customer_of(runtime)
    if customer_id is None:
        return {"error": config.NO_IDENTITY}
    return readable(refunds.find(customer_id, track, artist, wont_play_on, latest))


@tool
def list_purchases(runtime: ToolRuntime[CustomerContext]) -> dict:
    """List this customer's most recent purchases, newest first, each with a purchase_ref."""
    customer_id = customer_of(runtime)
    if customer_id is None:
        return {"error": config.NO_IDENTITY}
    lines = catalog.customer_purchases(customer_id)
    return readable({
        "total": len(lines),
        "purchases": [{"purchase_ref": refunds.purchase_ref(customer_id, line["invoice_line_id"]),
                       "label": refunds.label(line), "format": line["media_type"]}
                      for line in lines[: config.MAX_LISTED_PURCHASES]],
    })


@tool
def request_refund(
    runtime: ToolRuntime[CustomerContext],
    purchase_ref: str,
    reason: RefundReason,
    action: Literal["refund", "swap"] = "refund",
    replacement_track_id: int | None = None,
    device: Device | None = None,
    details: str | None = None,
) -> dict:
    """Refund or swap one purchase, by the purchase_ref from find_purchases.

    The customer confirms first. The store's refund policy decides the outcome.
    """
    customer_id = customer_of(runtime)
    if customer_id is None:
        return {"error": config.NO_IDENTITY}
    line = refunds.purchase_for_ref(customer_id, purchase_ref)
    if line is None:
        return {"error": config.NOT_YOUR_PURCHASE}
    if details and len(details) > config.MAX_REASON:
        return {"error": f"details must be at most {config.MAX_REASON} characters."}
    if (action == "swap") != (replacement_track_id is not None):
        return {"error": "a swap needs a replacement track, and a refund cannot name one."}
    if store.has_live_request(line["invoice_line_id"]):
        return {"error": config.ALREADY_REQUESTED}

    if action == "swap":
        problem = catalog.check_swap(customer_id, line["track_id"], replacement_track_id)
        if problem:
            return {"error": problem}
        # A valid swap moves no money, so it is approved without scoring.
        decision = {"status": "auto_approved", "score": None, "items": {}, "policy": config.REFUND_POLICY_VERSION}
    else:
        decision = refunds.decide(customer_id, line, reason, device)

    thread_id = (runtime.config or {}).get("configurable", {}).get("thread_id", "")
    try:
        store.record(
            store.request_key(str(thread_id), str(runtime.tool_call_id)),
            customer_id=customer_id, invoice_line_id=line["invoice_line_id"], track_id=line["track_id"],
            action=action, replacement_track_id=replacement_track_id, amount=str(line["unit_price"]),
            reason=reason if not details else f"{reason}: {details.strip()}",
            status=decision["status"], score=decision["score"], policy=decision["policy"])
    except Exception:
        return {"error": config.REQUEST_NOT_DONE}
    outcomes.record_refund(decision["status"], action, str(line["unit_price"]))
    message = config.SWAP_APPROVED if action == "swap" else config.REFUND_MESSAGES[decision["status"]]
    return {"status": decision["status"], "action": action, "track": line["track"],
            "amount": str(line["unit_price"]), "message": message,
            "failed_checks": [name for name, passed in decision["items"].items() if not passed]}


def describe_refund(tool_call, state, runtime) -> str:
    """The confirmation the customer sees: the exact item, price, and reason."""
    args, customer_id = tool_call["args"], customer_of(runtime)
    line = refunds.purchase_for_ref(customer_id, args.get("purchase_ref", "")) if customer_id else None
    if line is None:
        return "This purchase could not be found on your account."
    verb = "Swap" if args.get("action") == "swap" else "Refund"
    why = config.REFUND_REASON_LABELS.get(args.get("reason"), "no reason given")
    return f"{verb} {line['track']} (${line['unit_price']}, bought {line['invoice_date']}) because {why}?"


APPROVAL_TEXT = {"request_refund": describe_refund}

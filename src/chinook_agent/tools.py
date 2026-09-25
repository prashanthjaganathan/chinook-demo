from decimal import Decimal

from langchain.tools import ToolRuntime, tool

from chinook_agent import db, pricing, support_db
from chinook_agent.context import CustomerContext

NO_PURCHASES = {"error": "There are no purchases on this account yet."}
NOT_YOUR_PURCHASE = {"error": "That track is not on this account."}
ACTIONS = ("refund", "swap")
MAX_REASON = 500
NO_IDENTITY = {"error": "I cannot see who is signed in, so I cannot open this account."}


def customer_of(runtime: ToolRuntime[CustomerContext]) -> int | None:
    # Runtime context is not carried across an approval resume, so it can be absent.
    return getattr(runtime.context, "customer_id", None)


def readable(value):
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {key: readable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [readable(item) for item in value]
    return value


@tool
def get_my_library(runtime: ToolRuntime[CustomerContext]) -> list[dict]:
    """List the tracks this customer already owns.

    Takes no arguments; the customer comes from the signed-in session.
    Returns each track with its album, artist, genre, format, and price.
    """
    customer_id = customer_of(runtime)
    if customer_id is None:
        return dict(NO_IDENTITY)
    return readable(db.get_library(customer_id))


@tool
def get_invoice(
    runtime: ToolRuntime[CustomerContext], invoice_id: int | None = None
) -> dict:
    """Read one of this customer's own past purchases, newest by default.

    Returns the date, the total, and every line with the price actually paid and
    the file format. Another customer's invoice reads as not found.
    """
    customer_id = customer_of(runtime)
    if customer_id is None:
        return dict(NO_IDENTITY)
    if invoice_id is None:
        invoice_id = db.latest_invoice_id(customer_id)
        if invoice_id is None:
            return dict(NO_PURCHASES)
    return readable(db.get_invoice(customer_id, invoice_id))


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
    """Search the store catalog by track, album, artist, genre, or file format.

    Set exclude_owned to hide what this customer already owns, for example when
    looking for a replacement. Returns matching tracks with format and price.
    """
    return readable(
        db.search_catalog(
            track=track,
            album=album,
            artist=artist,
            genre=genre,
            media_type=media_type,
            exclude_owned_for=customer_of(runtime) if exclude_owned else None,
            limit=limit,
        )
    )


def offer(customer_id: int, album: dict, with_tracks: bool) -> dict:
    missing = db.missing_tracks(customer_id, album["album_id"])
    priced = {
        **album,
        **pricing.completion_price([track["unit_price"] for track in missing]),
        "missing_count": len(missing),
    }
    if with_tracks:
        priced["missing_tracks"] = missing
    return priced


@tool
def price_completion(
    runtime: ToolRuntime[CustomerContext],
    album_id: int | None = None,
    limit: int = 5,
) -> list[dict]:
    """Price finishing an album this customer has already started buying.

    With no album_id, lists the albums closest to complete and what each costs.
    With an album_id, also names the exact tracks they are missing. Every price
    already includes the completion discount.
    """
    customer_id = customer_of(runtime)
    if customer_id is None:
        return [dict(NO_IDENTITY)]
    albums = db.partial_albums(customer_id)
    if album_id is not None:
        albums = [album for album in albums if album["album_id"] == album_id]
    return readable(
        [offer(customer_id, album, album_id is not None) for album in albums[:limit]]
    )


@tool
def request_refund_or_swap(
    runtime: ToolRuntime[CustomerContext],
    track_id: int,
    action: str,
    reason: str,
    replacement_track_id: int | None = None,
) -> dict:
    """Raise a refund or a replacement for a track this customer bought.

    action is "refund" or "swap"; a swap needs replacement_track_id. The refund
    amount is taken from the original purchase, never from the conversation.
    A human reviews this before anything is written.
    """
    customer_id = customer_of(runtime)
    if customer_id is None:
        return dict(NO_IDENTITY)
    if action not in ACTIONS:
        return {"error": f"action must be one of {' or '.join(ACTIONS)}."}
    if not reason or not reason.strip() or len(reason) > MAX_REASON:
        return {"error": f"reason must be 1 to {MAX_REASON} characters."}
    if action == "swap" and replacement_track_id is None:
        return {"error": "a swap needs a replacement track."}
    if action == "refund" and replacement_track_id is not None:
        return {"error": "a refund cannot name a replacement track."}

    purchase = db.purchase_of(customer_id, track_id)
    if purchase is None:
        return dict(NOT_YOUR_PURCHASE)

    if action == "swap":
        problem = db.check_swap(customer_id, track_id, replacement_track_id)
        if problem:
            return {"error": problem}

    try:
        recorded = support_db.record(
            support_db.request_key(
                str((runtime.config or {}).get("configurable", {}).get("thread_id", "")),
                str(runtime.tool_call_id),
            ),
            customer_id=customer_id,
            invoice_line_id=purchase["invoice_line_id"],
            track_id=track_id,
            action=action,
            replacement_track_id=replacement_track_id,
            amount=str(purchase["unit_price"]),
            reason=reason.strip(),
        )
    except Exception as error:
        return {"error": f"The request was not completed: {error}"}

    return readable(
        {
            "status": recorded["status"],
            "action": recorded["action"],
            "track": purchase["track"],
            "amount": recorded["amount"],
            "request_key": recorded["request_key"],
        }
    )


TOOLS = [
    get_my_library,
    get_invoice,
    search_catalog,
    price_completion,
    request_refund_or_swap,
]

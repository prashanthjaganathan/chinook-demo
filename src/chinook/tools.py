from decimal import Decimal

from langchain.tools import ToolRuntime, tool

from chinook import catalog, config, pricing
from chinook.context import CustomerContext


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


@tool
def get_my_library(runtime: ToolRuntime[CustomerContext]) -> list[dict] | dict:
    """List the tracks this customer already owns, with album, artist, genre, format, and price."""
    customer_id = customer_of(runtime)
    if customer_id is None:
        return {"error": config.NO_IDENTITY}
    return readable(catalog.get_library(customer_id))


@tool
def get_invoice(runtime: ToolRuntime[CustomerContext], invoice_id: int | None = None) -> dict:
    """Read one of this customer's past purchases, newest by default.

    Returns the date, total, and each line with the price paid and the file format.
    """
    customer_id = customer_of(runtime)
    if customer_id is None:
        return {"error": config.NO_IDENTITY}
    invoice_id = invoice_id or catalog.latest_invoice_id(customer_id)
    if invoice_id is None:
        return {"error": config.NO_PURCHASES}
    return readable(catalog.get_invoice(customer_id, invoice_id))


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


@tool
def price_completion(
    runtime: ToolRuntime[CustomerContext], album_id: int | None = None, limit: int = 5
) -> list[dict]:
    """Price finishing albums this customer has started buying, closest to complete first.

    With an album_id, also lists the missing tracks. Prices include the completion discount.
    """
    customer_id = customer_of(runtime)
    if customer_id is None:
        return [{"error": config.NO_IDENTITY}]
    albums = catalog.partial_albums(customer_id)
    if album_id is not None:
        albums = [a for a in albums if a["album_id"] == album_id]
    offers = []
    for album in albums[:limit]:
        missing = catalog.missing_tracks(customer_id, album["album_id"])
        offer = {**album, **pricing.completion_price([t["unit_price"] for t in missing]),
                 "missing_count": len(missing)}
        if album_id is not None:
            offer["missing_tracks"] = missing
        offers.append(offer)
    return readable(offers)

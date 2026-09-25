from decimal import Decimal

from langchain.tools import ToolRuntime

from chinook_agent import db, pricing
from chinook_agent.context import CustomerContext
from chinook_agent.prompt import SYSTEM_PROMPT
from chinook_agent.tools import price_completion

STAR = 48
IN_STEP = 205


def runtime_for(customer_id):
    return ToolRuntime(
        state={},
        context=CustomerContext(customer_id=customer_id),
        config={},
        stream_writer=lambda *args, **kwargs: None,
        tool_call_id="test",
        store=None,
    )


def offers(customer_id, **kwargs):
    return price_completion.invoke({"runtime": runtime_for(customer_id), **kwargs})


def test_price_tool_matches_pricing_rule():
    offer = offers(STAR, album_id=IN_STEP)[0]
    missing = db.missing_tracks(STAR, IN_STEP)
    expected = pricing.completion_price([track["unit_price"] for track in missing])

    assert offer["list_price"] == str(expected["list_price"])
    assert offer["discount"] == str(expected["discount"])
    assert offer["final_price"] == str(expected["final_price"])


def test_the_star_customer_offer_is_the_demo_numbers():
    offer = offers(STAR, album_id=IN_STEP)[0]

    assert (offer["owned_tracks"], offer["total_tracks"]) == (4, 10)
    assert offer["missing_count"] == 6
    assert (offer["list_price"], offer["discount"], offer["final_price"]) == (
        "5.94",
        "1.19",
        "4.75",
    )


def test_listing_omits_track_names_but_detail_includes_them():
    listed = offers(STAR)[0]
    detailed = offers(STAR, album_id=IN_STEP)[0]

    assert "missing_tracks" not in listed
    assert [track["track"] for track in detailed["missing_tracks"]]
    assert len(detailed["missing_tracks"]) == detailed["missing_count"]


def test_price_tool_never_offers_a_fully_owned_album(chinook_db):
    import sqlite3

    connection = sqlite3.connect(chinook_db)
    try:
        customer_id, album_id = connection.execute(
            """
            SELECT i.CustomerId, t.AlbumId
            FROM Invoice i
            JOIN InvoiceLine il ON il.InvoiceId = i.InvoiceId
            JOIN Track t ON t.TrackId = il.TrackId
            GROUP BY i.CustomerId, t.AlbumId
            HAVING COUNT(DISTINCT t.TrackId)
                   = (SELECT COUNT(*) FROM Track WHERE AlbumId = t.AlbumId)
            LIMIT 1
            """
        ).fetchone()
    finally:
        connection.close()

    assert offers(customer_id, album_id=album_id) == []


def test_price_tool_never_includes_an_owned_track():
    owned = {track["track_id"] for track in db.get_library(STAR)}

    for offer in offers(STAR, album_id=IN_STEP):
        assert {track["track_id"] for track in offer["missing_tracks"]}.isdisjoint(owned)


def test_offers_are_ordered_closest_to_complete_first():
    ratios = [
        offer["owned_tracks"] / offer["total_tracks"] for offer in offers(STAR, limit=50)
    ]

    assert ratios == sorted(ratios, reverse=True)


def test_limit_bounds_the_listing():
    assert len(offers(STAR, limit=2)) == 2


def test_unknown_album_offers_nothing():
    assert offers(STAR, album_id=999999) == []


def test_prices_reach_the_model_as_exact_strings():
    offer = offers(STAR, album_id=IN_STEP)[0]

    assert all(
        isinstance(offer[field], str)
        for field in ("list_price", "discount", "final_price")
    )
    assert Decimal(offer["final_price"]) + Decimal(offer["discount"]) == Decimal(
        offer["list_price"]
    )


def test_prompt_forbids_inventing_a_price():
    assert "must come from a tool result" in SYSTEM_PROMPT
    assert "price_completion" in SYSTEM_PROMPT
    assert "already own in full" in SYSTEM_PROMPT

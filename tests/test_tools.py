from decimal import Decimal

from helpers import runtime_for

from chinook import catalog, config, pricing
from chinook.tools import (
    get_invoice, get_my_library, price_completion, readable, search_catalog,
)

TOOLS = (get_my_library, get_invoice, search_catalog, price_completion)


def run(tool, customer_id, **args):
    return tool.invoke({"runtime": runtime_for(customer_id), **args})


def test_no_tool_accepts_customer_id():
    for tool in TOOLS:
        fields = set(tool.tool_call_schema.model_fields)
        assert not {"customer_id", "customer", "user_id", "runtime", "exclude_owned_for"} & fields


def test_tools_read_the_customer_from_context():
    mine = {r["track_id"] for r in run(get_my_library, 54)}

    assert mine == {r["track_id"] for r in catalog.get_library(54)}
    assert mine != {r["track_id"] for r in run(get_my_library, 1)}


def test_missing_context_gets_the_fixed_no_identity_result():
    assert run(get_my_library, None) == {"error": config.NO_IDENTITY}
    assert run(get_invoice, None) == {"error": config.NO_IDENTITY}
    assert run(price_completion, None) == [{"error": config.NO_IDENTITY}]


def test_invoice_tool_hides_foreign_invoices_and_defaults_to_latest():
    assert run(get_invoice, 1, invoice_id=293) == run(get_invoice, 1, invoice_id=999999)
    assert run(get_invoice, 1)["invoice_id"] == 382
    assert run(get_invoice, 999999) == {"error": config.NO_PURCHASES}


def test_exclude_owned_uses_the_session_customer():
    offered = run(search_catalog, 4, artist="AC/DC", exclude_owned=True, limit=50)

    assert len(offered) == 14


def test_prices_reach_the_model_as_exact_strings():
    assert readable({"total": Decimal("8.91"), "lines": [{"unit_price": Decimal("0.99")}]}) == {
        "total": "8.91", "lines": [{"unit_price": "0.99"}]}
    assert all(r["unit_price"] == "0.99" for r in run(get_my_library, 54))


def test_price_completion_matches_the_pricing_rule_for_customer_48():
    offer = run(price_completion, 48, album_id=205)[0]
    expected = pricing.completion_price([t["unit_price"] for t in catalog.missing_tracks(48, 205)])

    assert (offer["owned_tracks"], offer["total_tracks"], offer["missing_count"]) == (4, 10, 6)
    assert offer["final_price"] == str(expected["final_price"]) == "4.75"
    assert len(offer["missing_tracks"]) == 6


def test_price_completion_listing_omits_track_names_and_respects_limit():
    offers = run(price_completion, 48, limit=2)

    assert len(offers) == 2 and "missing_tracks" not in offers[0]
    assert run(price_completion, 48, album_id=999999) == []

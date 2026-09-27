from decimal import Decimal

from helpers import runtime_for

from chinook.agent.tools import (
    buy_completion,
    find_purchases,
    list_purchases,
    readable,
    recommend_engine,
    request_refund,
    search_catalog,
)
from chinook.domain import refunds
from chinook.foundation import config
from chinook.helpers import catalog, pricing, store

TOOLS = (list_purchases, find_purchases, search_catalog, recommend_engine, buy_completion, request_refund)


def run(tool, customer_id, **args):
    return tool.invoke({"runtime": runtime_for(customer_id), **args})


def test_no_tool_accepts_customer_id():
    for tool in TOOLS:
        fields = set(tool.tool_call_schema.model_fields)
        assert not {"customer_id", "customer", "user_id", "runtime", "exclude_owned_for"} & fields


def test_tools_read_the_customer_from_context():
    assert run(find_purchases, 54, track="midnight")["status"] == "found"
    assert run(find_purchases, 1, track="midnight")["status"] == "not_found"


def test_missing_context_gets_the_fixed_no_identity_result():
    assert run(find_purchases, None) == {"error": config.NO_IDENTITY}
    assert run(list_purchases, None) == {"error": config.NO_IDENTITY}
    assert run(request_refund, None, purchase_ref="x", reason="other") == {"error": config.NO_IDENTITY}
    assert run(recommend_engine, None) == {"error": config.NO_IDENTITY}
    assert run(buy_completion, None, offer_id="x") == {"error": config.NO_IDENTITY}


def test_exclude_owned_uses_the_session_customer():
    offered = run(search_catalog, 4, artist="AC/DC", exclude_owned=True, limit=50)

    assert len(offered) == 14


def test_prices_reach_the_model_as_exact_strings():
    assert readable({"total": Decimal("8.91"), "lines": [{"unit_price": Decimal("0.99")}]}) == {
        "total": "8.91", "lines": [{"unit_price": "0.99"}]}
    assert "$0.99" in run(find_purchases, 54, track="midnight")["purchases"][0]["label"]


def in_step_offer():
    return run(recommend_engine, 48)["offers"][0]


def test_recommend_engine_prices_in_step_for_customer_48():
    offer = in_step_offer()
    expected = pricing.completion_price([t["unit_price"] for t in catalog.missing_tracks(48, 205)])

    assert (offer["owned_tracks"], offer["total_tracks"], len(offer["missing_tracks"])) == (4, 10, 6)
    assert offer["final_price"] == str(expected["final_price"]) == "4.75"


def test_recommend_engine_saves_stated_taste():
    result = run(recommend_engine, 48,
                 new_preferences={"device": "other", "genres": ["blues"]})

    assert result["saved_preferences"] == {"device": "other", "genres": ["Blues"], "artists": []}


def test_buy_completion_refuses_a_changed_or_foreign_offer():
    offer_id = in_step_offer()["offer_id"]

    assert run(buy_completion, 48, offer_id="205-stale") == {"error": config.OFFER_CHANGED}
    assert run(buy_completion, 54, offer_id=offer_id) == {"error": config.OFFER_CHANGED}


def test_a_replayed_purchase_records_one_order():
    offer_id = in_step_offer()["offer_id"]
    first = run(buy_completion, 48, offer_id=offer_id)
    again = run(buy_completion, 48, offer_id=offer_id)

    assert first == again == {"status": "confirmed", "album": "In Step", "tracks": 6, "amount": "4.75"}
    assert len(store.execute("SELECT * FROM orders")) == 1


def test_list_purchases_shows_only_own_purchases_newest_first_with_usable_refs():
    listed = run(list_purchases, 54)
    lines = catalog.customer_purchases(54)

    assert listed["total"] == len(lines)
    assert len(listed["purchases"]) == min(len(lines), config.MAX_LISTED_PURCHASES)
    assert listed["purchases"][0]["label"] == refunds.label(lines[0])
    assert all(refunds.purchase_for_ref(54, p["purchase_ref"]) for p in listed["purchases"])
    assert not any(refunds.purchase_for_ref(1, p["purchase_ref"]) for p in listed["purchases"])

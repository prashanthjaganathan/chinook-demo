from decimal import Decimal

from langchain.tools import ToolRuntime

from chinook_agent import db
from chinook_agent.context import CustomerContext
from chinook_agent.tools import (
    TOOLS,
    get_invoice,
    get_my_library,
    readable,
    search_catalog,
)


def runtime_for(customer_id):
    return ToolRuntime(
        state={},
        context=CustomerContext(customer_id=customer_id),
        config={},
        stream_writer=lambda *args, **kwargs: None,
        tool_call_id="test",
        store=None,
    )


def test_no_tool_exposes_an_identity_argument():
    for tool in TOOLS:
        fields = set(tool.tool_call_schema.model_fields)

        assert not {"customer_id", "customer", "user_id", "runtime"} & fields


def test_get_my_library_takes_no_arguments_at_all():
    assert list(get_my_library.tool_call_schema.model_fields) == []


def test_tool_reads_the_customer_from_context():
    rows = get_my_library.invoke({"runtime": runtime_for(54)})

    assert {row["track_id"] for row in rows} == {
        row["track_id"] for row in db.get_library(54)
    }


def test_a_different_context_returns_a_different_library():
    mine = get_my_library.invoke({"runtime": runtime_for(54)})
    theirs = get_my_library.invoke({"runtime": runtime_for(1)})

    assert {row["track_id"] for row in mine} != {row["track_id"] for row in theirs}


def test_prices_are_sent_to_the_model_as_exact_strings():
    rows = get_my_library.invoke({"runtime": runtime_for(54)})

    assert all(row["unit_price"] == "0.99" for row in rows)
    assert all(isinstance(row["unit_price"], str) for row in rows)


def test_readable_leaves_non_money_values_alone():
    rows = readable([{"track_id": 1, "unit_price": Decimal("1.99"), "track": "x"}])

    assert rows == [{"track_id": 1, "unit_price": "1.99", "track": "x"}]


def test_readable_reaches_prices_nested_inside_an_invoice():
    invoice = readable(
        {"total": Decimal("8.91"), "lines": [{"unit_price": Decimal("0.99")}]}
    )

    assert invoice == {"total": "8.91", "lines": [{"unit_price": "0.99"}]}


def test_every_tool_is_registered():
    assert [tool.name for tool in TOOLS] == [
        "get_my_library",
        "get_invoice",
        "search_catalog",
        "price_completion",
        "request_refund_or_swap",
    ]


def test_invoice_tool_reads_an_owned_invoice():
    invoice = get_invoice.invoke({"runtime": runtime_for(1), "invoice_id": 382})

    assert invoice["total"] == "8.91"
    assert len(invoice["lines"]) == 9


def test_invoice_tool_hides_foreign_invoices():
    foreign = get_invoice.invoke({"runtime": runtime_for(1), "invoice_id": 293})
    missing = get_invoice.invoke({"runtime": runtime_for(1), "invoice_id": 999999})

    assert foreign == missing == db.INVOICE_NOT_FOUND
    assert "293" not in str(foreign)


def test_invoice_tool_defaults_to_the_most_recent_purchase():
    latest = get_invoice.invoke({"runtime": runtime_for(1)})

    assert latest["invoice_id"] == db.latest_invoice_id(1)
    assert latest["invoice_date"] == "2025-08-07"


def test_invoice_tool_on_a_customer_with_no_purchases():
    assert get_invoice.invoke({"runtime": runtime_for(999999)})["error"]


def test_search_tool_finds_tracks():
    rows = search_catalog.invoke({"runtime": runtime_for(4), "artist": "AC/DC", "limit": 50})

    assert len(rows) == 18


def test_exclude_owned_uses_the_session_customer():
    owned = {row["track_id"] for row in db.get_library(4)}
    offered = search_catalog.invoke(
        {"runtime": runtime_for(4), "artist": "AC/DC", "exclude_owned": True, "limit": 50}
    )

    assert {row["track_id"] for row in offered}.isdisjoint(owned)
    assert len(offered) == 14


def test_exclude_owned_cannot_be_pointed_at_another_customer():
    fields = set(search_catalog.tool_call_schema.model_fields)

    assert "exclude_owned" in fields
    assert not {"exclude_owned_for", "customer_id"} & fields


def test_exclude_owned_is_per_session():
    mine = search_catalog.invoke(
        {"runtime": runtime_for(4), "artist": "AC/DC", "exclude_owned": True, "limit": 50}
    )
    theirs = search_catalog.invoke(
        {"runtime": runtime_for(1), "artist": "AC/DC", "exclude_owned": True, "limit": 50}
    )

    assert {row["track_id"] for row in mine} != {row["track_id"] for row in theirs}


def test_injection_through_the_search_tool_matches_nothing():
    for text in ("' OR 1=1 --", '"; DROP TABLE Track; --'):
        assert search_catalog.invoke({"runtime": runtime_for(4), "artist": text}) == []


def test_search_tool_limit_is_capped():
    rows = search_catalog.invoke({"runtime": runtime_for(4), "limit": 10_000})

    assert len(rows) == db.MAX_SEARCH_RESULTS

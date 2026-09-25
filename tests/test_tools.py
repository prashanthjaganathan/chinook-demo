from decimal import Decimal

from langchain.tools import ToolRuntime

from chinook_agent import db
from chinook_agent.context import CustomerContext
from chinook_agent.tools import TOOLS, get_my_library, readable


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

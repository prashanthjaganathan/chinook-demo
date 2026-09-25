import pytest
from langchain.tools import ToolRuntime

from chinook_agent import db, support_db
from chinook_agent.context import CustomerContext
from chinook_agent.tools import NOT_YOUR_PURCHASE, request_refund_or_swap

CUSTOMER = 54
PROTECTED_TRACK = 1504
GOOD_REPLACEMENT = 1
FOREIGN_TRACK = 3503


@pytest.fixture(autouse=True)
def scratch_db(tmp_path, monkeypatch):
    monkeypatch.setenv("SUPPORT_DB", str(tmp_path / "support.sqlite"))


def runtime_for(customer_id, thread="t1", call="c1"):
    return ToolRuntime(
        state={},
        context=CustomerContext(customer_id=customer_id),
        config={"configurable": {"thread_id": thread}},
        stream_writer=lambda *args, **kwargs: None,
        tool_call_id=call,
        store=None,
    )


def ask(customer_id=CUSTOMER, thread="t1", call="c1", **kwargs):
    payload = {
        "track_id": PROTECTED_TRACK,
        "action": "refund",
        "reason": "will not play on Android",
        **kwargs,
    }
    return request_refund_or_swap.invoke(
        {"runtime": runtime_for(customer_id, thread, call), **payload}
    )


def test_a_refund_is_recorded():
    result = ask()

    assert result["status"] == "open"
    assert result["action"] == "refund"
    assert len(support_db.open_requests(CUSTOMER)) == 1


def test_refund_amount_comes_from_the_invoice_line_not_the_model():
    paid = db.purchase_of(CUSTOMER, PROTECTED_TRACK)["unit_price"]

    assert ask()["amount"] == str(paid)
    assert "amount" not in request_refund_or_swap.tool_call_schema.model_fields


def test_refund_on_a_track_the_customer_never_bought_is_refused():
    assert ask(track_id=FOREIGN_TRACK) == NOT_YOUR_PURCHASE
    assert support_db.open_requests(CUSTOMER) == []


def test_another_customers_purchase_is_refused_identically():
    mine = ask(customer_id=1, track_id=PROTECTED_TRACK)
    missing = ask(customer_id=1, track_id=FOREIGN_TRACK)

    assert mine == missing == NOT_YOUR_PURCHASE
    assert support_db.open_requests(1) == []


def test_action_must_be_refund_or_swap():
    for action in ("delete", "", "REFUND ", "cancel"):
        assert "error" in ask(action=action)

    assert support_db.open_requests(CUSTOMER) == []


def test_swap_requires_a_replacement_and_refund_forbids_one():
    assert "error" in ask(action="swap")
    assert "error" in ask(action="refund", replacement_track_id=GOOD_REPLACEMENT)
    assert support_db.open_requests(CUSTOMER) == []


def test_reason_length_is_bounded():
    for reason in ("", "   ", "x" * 501):
        assert "error" in ask(reason=reason)

    assert support_db.open_requests(CUSTOMER) == []


def test_a_valid_swap_is_recorded():
    result = ask(action="swap", replacement_track_id=GOOD_REPLACEMENT)

    assert result["status"] == "open"
    assert result["action"] == "swap"


def test_an_invalid_swap_is_refused_and_nothing_is_recorded():
    protected = db.search_catalog(
        media_type="Protected AAC", exclude_owned_for=CUSTOMER, limit=1
    )[0]

    assert "error" in ask(action="swap", replacement_track_id=protected["track_id"])
    assert support_db.open_requests(CUSTOMER) == []


def test_replaying_the_same_tool_call_writes_once():
    ask()
    ask()

    assert len(support_db.open_requests(CUSTOMER)) == 1


def test_a_second_thread_cannot_refund_the_same_line():
    ask(thread="t1")
    second = ask(thread="t2", call="c2")

    assert "not completed" in second["error"]
    assert len(support_db.open_requests(CUSTOMER)) == 1


def test_two_parallel_calls_for_one_line_write_once():
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(lambda index: ask(thread=f"t{index}", call=f"c{index}"), (1, 2))
        )

    assert len(support_db.open_requests(CUSTOMER)) == 1
    assert sum("error" in result for result in results) == 1


def test_a_store_failure_is_reported_as_not_done(monkeypatch):
    monkeypatch.setattr(
        support_db, "record", lambda *a, **k: (_ for _ in ()).throw(OSError("disk gone"))
    )
    result = ask()

    assert "not completed" in result["error"]
    assert "status" not in result

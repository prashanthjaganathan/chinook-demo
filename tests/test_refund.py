from concurrent.futures import ThreadPoolExecutor

import pytest
from helpers import call, once_then, runtime_for
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from chinook import agents, catalog, config, store
from chinook.context import CustomerContext
from chinook.tools import request_refund_or_swap

PROTECTED, MP3 = 1504, 1


def ask(customer_id=54, thread="t1", call_id="c1", **args):
    payload = {"track_id": PROTECTED, "action": "refund", "reason": "will not play", **args}
    return request_refund_or_swap.invoke({"runtime": runtime_for(customer_id, thread, call_id), **payload})


def test_the_amount_comes_from_the_invoice_line_not_the_model():
    assert ask()["amount"] == str(catalog.purchase_of(54, PROTECTED)["unit_price"])
    assert "amount" not in request_refund_or_swap.tool_call_schema.model_fields


def test_a_foreign_purchase_is_refused_and_nothing_is_recorded():
    assert ask(customer_id=1) == ask(customer_id=1, track_id=3503) == {"error": config.NOT_YOUR_PURCHASE}
    assert store.open_requests(1) == []


@pytest.mark.parametrize("args", [
    {"action": "delete"}, {"reason": ""}, {"reason": "x" * 501},
    {"action": "swap"}, {"action": "refund", "replacement_track_id": MP3},
])
def test_invalid_requests_are_refused_and_nothing_is_recorded(args):
    assert "error" in ask(**args)
    assert store.open_requests(54) == []


def test_a_valid_swap_is_recorded_and_an_invalid_one_is_not():
    protected = catalog.search_catalog(media_type="Protected AAC", exclude_owned_for=54, limit=1)[0]

    assert "error" in ask(action="swap", replacement_track_id=protected["track_id"])
    assert ask(action="swap", replacement_track_id=MP3)["status"] == "needs_review"


def test_two_parallel_refunds_for_one_line_write_once():
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda n: ask(thread=f"t{n}", call_id=f"c{n}"), (1, 2)))

    assert len(store.open_requests(54)) == 1
    assert sum("error" in r for r in results) == 1


def test_a_store_failure_is_reported_as_not_done(monkeypatch):
    monkeypatch.setattr(store, "record", lambda *a, **k: (_ for _ in ()).throw(OSError("disk gone")))

    assert ask() == {"error": config.REQUEST_NOT_DONE}


def approval_agent():
    model = once_then(call("request_refund_or_swap",
                           {"track_id": PROTECTED, "action": "refund", "reason": "will not play"}))
    return agents.build_subagent(agents.spec_named("invoice_support"), model=model,
                                 checkpointer=InMemorySaver())


def start(agent):
    config_ = {"configurable": {"thread_id": "t1"}}
    result = agent.invoke({"messages": [{"role": "user", "content": "refund it"}]},
                          config=config_, context=CustomerContext(customer_id=54))
    return result, config_


def resume(agent, config_, payload):
    return agent.invoke(Command(resume=payload), config=config_, context=CustomerContext(customer_id=54))


def test_the_write_pauses_for_approval_before_anything_is_recorded():
    result, _ = start(approval_agent())

    assert "__interrupt__" in result and store.open_requests(54) == []


def test_approve_writes_one_request_and_reject_writes_none():
    agent = approval_agent()
    _, config_ = start(agent)
    resume(agent, config_, {"decisions": [{"type": "approve"}]})
    assert len(store.open_requests(54)) == 1

    other = approval_agent()
    _, config_ = start(other)
    resume(other, config_, {"decisions": [{"type": "reject"}]})
    assert len(store.open_requests(54)) == 1


def test_approval_allows_only_approve_and_reject():
    hitl = agents.approval(agents.spec_named("invoice_support"))[0]
    allowed = hitl.interrupt_on["request_refund_or_swap"]

    assert set(allowed["allowed_decisions"] if isinstance(allowed, dict) else allowed.allowed_decisions) == {
        "approve", "reject"}
    assert agents.approval(agents.spec_named("music_recommendation"))[0].interrupt_on["buy_completion"]


@pytest.mark.parametrize("bad", ["", {"decisions": "approve"}])
def test_a_malformed_resume_breaks_the_thread_for_good(bad):
    # Known LangChain behaviour: the bad payload is checkpointed and every later resume replays it.
    agent = approval_agent()
    _, config_ = start(agent)

    with pytest.raises(Exception):
        resume(agent, config_, bad)
    with pytest.raises(Exception):
        resume(agent, config_, {"decisions": [{"type": "approve"}]})
    assert store.open_requests(54) == []

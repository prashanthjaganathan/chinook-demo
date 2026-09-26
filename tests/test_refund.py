import os
from typing import get_args

import pytest
from helpers import once_then, ref, refund_call, runtime_for
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from chinook.assembly import agents
from chinook.assembly.tools import RefundReason, describe_refund, request_refund
from chinook.domain import refunds
from chinook.foundation import config
from chinook.foundation.context import CustomerContext
from chinook.helpers import catalog, store

MP3 = 1


def ask(customer_id=54, thread="t1", call_id="c1", **args):
    payload = {"purchase_ref": ref(), "reason": "wont_play", "device": "other", **args}
    return request_refund.invoke({"runtime": runtime_for(customer_id, thread, call_id), **payload})


def test_the_reason_codes_match_the_policy():
    assert get_args(RefundReason) == tuple(config.REFUND_REASON_LABELS)


def test_the_amount_comes_from_the_invoice_line_not_the_model():
    line = refunds.purchase_for_ref(54, ref())

    assert ask()["amount"] == str(line["unit_price"])
    assert "amount" not in request_refund.tool_call_schema.model_fields


def test_the_policy_decides_and_says_what_happened():
    result = ask()

    assert result["status"] == "auto_approved" and result["message"] == config.REFUND_MESSAGES["auto_approved"]
    assert store.open_requests(54)[0]["score"] == 100


def test_a_rejection_lists_the_failed_checks_and_an_appeal_goes_to_staff():
    rejected = ask(reason="didnt_like_it")
    appeal = ask(reason="other", details="appeal", call_id="c2")

    assert rejected["status"] == "auto_rejected"
    assert rejected["failed_checks"] == ["reason_is_refundable", "data_supports_reason"]
    assert appeal["status"] == "needs_review"


def test_a_foreign_or_made_up_ref_is_refused_and_nothing_is_recorded():
    assert ask(customer_id=1) == ask(purchase_ref="1-0000000000") == {"error": config.NOT_YOUR_PURCHASE}
    assert store.open_requests(1) == store.open_requests(54) == []


@pytest.mark.parametrize("args", [
    {"details": "x" * 501}, {"action": "swap"}, {"action": "refund", "replacement_track_id": MP3},
])
def test_invalid_requests_are_refused_and_nothing_is_recorded(args):
    assert "error" in ask(**args)
    assert store.open_requests(54) == []


def test_a_swap_is_approved_only_when_the_swap_rules_pass():
    protected = catalog.search_catalog(media_type="Protected AAC", exclude_owned_for=54, limit=1)[0]

    assert "error" in ask(action="swap", replacement_track_id=protected["track_id"])
    swapped = ask(action="swap", replacement_track_id=MP3)
    assert (swapped["status"], swapped["message"]) == ("auto_approved", config.SWAP_APPROVED)


def test_a_second_request_on_the_same_purchase_is_told_it_is_in_progress():
    ask()

    assert ask(call_id="c2") == {"error": config.ALREADY_REQUESTED}
    assert ask(call_id="c3", action="swap", replacement_track_id=MP3) == {"error": config.ALREADY_REQUESTED}
    assert len(store.open_requests(54)) == 1


def test_a_replayed_call_records_once():
    ask(reason="didnt_like_it")
    ask(reason="didnt_like_it")

    assert len(store.open_requests(54)) == 1


def test_a_store_failure_is_reported_as_not_done(monkeypatch):
    monkeypatch.setattr(store, "record", lambda *a, **k: (_ for _ in ()).throw(OSError("disk gone")))

    assert ask() == {"error": config.REQUEST_NOT_DONE}


def test_the_confirmation_names_the_item_price_and_reason():
    tool_call = {"args": {"purchase_ref": ref(), "reason": "wont_play"}}
    date = refunds.purchase_for_ref(54, ref())["invoice_date"]

    assert describe_refund(tool_call, {}, runtime_for(54)) == (
        f"Refund Midnight ($0.99, bought {date}) because it won't play on my device?")
    assert describe_refund(tool_call, {}, runtime_for(1)) == "This purchase could not be found on your account."


def approval_agent():
    return agents.build_subagent(agents.spec_named("invoice_support"), model=once_then(refund_call()),
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
    resume(agent, config_, {"decisions": [{"type": "reject"}]})
    assert store.open_requests(54) == []

    other = approval_agent()
    _, config_ = start(other)
    resume(other, config_, {"decisions": [{"type": "approve"}]})
    assert len(store.open_requests(54)) == 1


def test_approval_allows_only_approve_and_reject():
    hitl = agents.approval(agents.spec_named("invoice_support"))[0]
    allowed = hitl.interrupt_on["request_refund"]

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


live = pytest.mark.skipif(not os.getenv("OPENAI_API_KEY"), reason="needs a real key")


def say(graph, text, thread, customer_id=54):
    payload = text if isinstance(text, Command) else {"messages": [{"role": "user", "content": text}]}
    return graph.invoke(payload, config={"configurable": {"thread_id": thread}},
                        context=CustomerContext(customer_id=customer_id))


def approve(graph, thread, customer_id=54):
    return say(graph, Command(resume={"decisions": [{"type": "approve"}]}), thread, customer_id)


def confirmation(result):
    return result["__interrupt__"][0].value["action_requests"][0]["description"]


@pytest.mark.live
@live
def test_live_midnight_on_android_is_auto_approved():
    graph = agents.build_supervisor(checkpointer=InMemorySaver())
    paused = say(graph, "Midnight won't play on my Android phone. Can I get a refund?", "live-midnight")

    assert confirmation(paused).startswith("Refund Midnight ($0.99")
    approve(graph, "live-midnight")
    assert [r["status"] for r in store.open_requests(54)] == ["auto_approved"]


@pytest.mark.live
@live
def test_live_an_ambiguous_artist_lists_choices_then_confirms_one():
    graph = agents.build_supervisor(checkpointer=InMemorySaver())
    first = say(graph, "Please refund the Metallica song.", "live-metallica", customer_id=42)
    assert "__interrupt__" not in first

    paused = say(graph, "The first one. I bought it by mistake.", "live-metallica", customer_id=42)
    metallica = {l["track"] for l in catalog.customer_purchases(42) if l["artist"] == "Metallica"}
    assert confirmation(paused).removeprefix("Refund ").split(" ($")[0] in metallica


@pytest.mark.live
@live
def test_live_a_vague_request_asks_which_and_why_in_one_turn():
    graph = agents.build_supervisor(checkpointer=InMemorySaver())
    result = say(graph, "I want a refund on this item.", "live-vague")
    answer = result["messages"][-1].text.lower()

    assert "__interrupt__" not in result
    assert "reason" in answer or "why" in answer


@pytest.mark.live
@live
def test_live_no_reason_is_asked_once_then_rejected_with_an_appeal_offer():
    graph = agents.build_supervisor(checkpointer=InMemorySaver())
    say(graph, "Please refund Midnight.", "live-no-reason")
    paused = say(graph, "Just refund it.", "live-no-reason")

    assert confirmation(paused).endswith("because no reason given?")
    done = approve(graph, "live-no-reason")["messages"][-1].text.lower()
    assert [r["status"] for r in store.open_requests(54)] == ["auto_rejected"]
    assert "replacement" in done or "person" in done or "team" in done

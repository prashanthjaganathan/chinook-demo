import json
import os

import pytest
from helpers import FakeModel, call, once_then, refund_call, tool_results
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from chinook.app import agents, prompts
from chinook.foundation.context import CustomerContext
from chinook.helpers import store

REFUND = refund_call()


def first_track_answer(messages):
    results = tool_results(messages)
    if not results:
        return call("find_purchases", {"track": "midnight"})
    return AIMessage(json.loads(results[0].content)["purchases"][0]["label"])


def supervisor(sup_model, sub_model, checkpointer=None, specs=agents.SUBAGENTS):
    return agents.build_supervisor(checkpointer=checkpointer, model=sup_model,
                                   subagent_model=sub_model, specs=specs)


def test_the_delegation_tool_takes_only_a_task():
    spec = agents.spec_named("music_recommendation")
    ask = agents.delegate(spec, agents.build_subagent(spec, model=once_then(AIMessage("hi"))))

    assert ask.name == "ask_music_recommendation"
    assert list(ask.tool_call_schema.model_fields) == ["task"]


def test_the_subagent_receives_the_parents_customer_and_returns_its_answer():
    graph = supervisor(once_then(call("ask_invoice_support", {"task": "what do I own?"}), "relayed"),
                       FakeModel(respond=first_track_answer))
    result = graph.invoke({"messages": [{"role": "user", "content": "hi"}]},
                          context=CustomerContext(customer_id=54))

    assert tool_results(result["messages"])[0].content.startswith("Midnight by ")
    assert result["messages"][-1].text == "relayed"


def test_the_supervisor_has_one_tool_per_specialist():
    graph = supervisor(once_then(AIMessage("hi")), once_then(AIMessage("hi")))
    tools = {name for name in graph.get_graph().nodes["tools"].data.tools_by_name}

    assert tools == {f"ask_{spec.name}" for spec in agents.SUBAGENTS}


def test_adding_a_spec_adds_a_tool_and_a_roster_line():
    extra = agents.AgentSpec("gift_cards", "Handles gift cards.", "You handle gift cards.", ())
    specs = agents.SUBAGENTS + (extra,)
    graph = supervisor(once_then(AIMessage("hi")), once_then(AIMessage("hi")), specs=specs)

    assert "ask_gift_cards" in graph.get_graph().nodes["tools"].data.tools_by_name
    assert "ask_gift_cards: Handles gift cards." in prompts.supervisor_prompt(specs)


def approval_run():
    graph = supervisor(once_then(call("ask_invoice_support", {"task": "refund Midnight"}), "sent"),
                       once_then(REFUND), checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": "T-9"}}
    result = graph.invoke({"messages": [{"role": "user", "content": "refund Midnight"}]},
                          config=config, context=CustomerContext(customer_id=54))
    return graph, config, result


def resume(graph, config, decision):
    return graph.invoke(Command(resume={"decisions": [{"type": decision}]}),
                        config=config, context=CustomerContext(customer_id=54))


def test_a_subagent_approval_pauses_at_the_top_level():
    _, _, result = approval_run()

    assert "__interrupt__" in result
    assert result["__interrupt__"][0].value["action_requests"][0]["name"] == "request_refund"
    assert store.open_requests(54) == []


def test_approve_through_the_supervisor_writes_one_request_keyed_by_the_real_thread():
    graph, config, _ = approval_run()
    result = resume(graph, config, "approve")
    rows = store.open_requests(54)

    assert len(rows) == 1 and result["messages"][-1].text == "sent"
    assert rows[0]["request_key"] == store.request_key("T-9", "call-1")


def test_reject_through_the_supervisor_writes_nothing():
    graph, config, _ = approval_run()
    resume(graph, config, "reject")

    assert store.open_requests(54) == []


def test_graph_entrypoint_has_no_checkpointer(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    assert agents.graph().checkpointer is None


@pytest.mark.live
@pytest.mark.skipif(not os.getenv("OPENAI_API_KEY"), reason="needs a real key")
def test_a_multi_intent_message_calls_both_specialists():
    graph = agents.build_supervisor(checkpointer=InMemorySaver())
    result = graph.invoke(
        {"messages": [{"role": "user", "content":
            "Midnight will not play on my Android, and what album am I closest to finishing?"}]},
        config={"configurable": {"thread_id": "live-multi"}}, context=CustomerContext(customer_id=54))
    # The refund pauses for the customer's confirmation before the second request is handled.
    while "__interrupt__" in result:
        result = graph.invoke(Command(resume={"decisions": [{"type": "approve"}]}),
                              config={"configurable": {"thread_id": "live-multi"}},
                              context=CustomerContext(customer_id=54))
    called = {c["name"] for m in result["messages"] for c in (getattr(m, "tool_calls", None) or [])}

    assert {"ask_invoice_support", "ask_music_recommendation"} <= called

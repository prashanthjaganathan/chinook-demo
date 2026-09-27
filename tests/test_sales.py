import json
import os

import pytest
from helpers import FakeModel, call, once_then, tool_results
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from chinook.agent import team
from chinook.domain import engine
from chinook.foundation.context import CustomerContext
from chinook.helpers import catalog, store

live = pytest.mark.skipif(not os.getenv("OPENAI_API_KEY"), reason="needs a real key")


def buys_the_first_offer(messages):
    results = tool_results(messages)
    if not results:
        return call("recommend_engine")
    if len(results) == 1:
        offer_id = json.loads(results[0].content)["offers"][0]["offer_id"]
        return call("buy_completion", {"offer_id": offer_id}, "call-2")
    return AIMessage(f"Done: ${json.loads(results[1].content)['amount']}")


def supervisor(sub_respond, task="buy In Step", model=None):
    return team.build_supervisor(
        checkpointer=InMemorySaver(),
        model=model or once_then(call("ask_music_recommendation", {"task": task}), "relayed"),
        subagent_model=FakeModel(respond=sub_respond))


def say(graph, text, thread="t-sales", customer_id=48):
    return graph.invoke(text if isinstance(text, Command) else {"messages": [{"role": "user", "content": text}]},
                        config={"configurable": {"thread_id": thread}},
                        context=CustomerContext(customer_id=customer_id))


def orders():
    return store.execute("SELECT * FROM orders")


def in_step_price():
    return str(engine.recommend(48)["offers"][0]["final_price"])


def test_a_purchase_is_recorded_once_without_an_approval_pause():
    result = say(supervisor(buys_the_first_offer), "yes, buy it")

    assert "__interrupt__" not in result
    assert [(o["album_id"], o["amount"]) for o in orders()] == [(205, in_step_price())]


def test_the_specialist_sees_recent_turns_of_the_conversation():
    seen = []

    def records_task(messages):
        seen.append(next(m.text for m in messages if isinstance(m, HumanMessage)))
        return AIMessage("Which one?")

    delegates_each_turn = FakeModel(respond=lambda m: call(
        "ask_music_recommendation", {"task": "recommend"}, f"c{len(m)}")
        if isinstance(m[-1], HumanMessage) else AIMessage(m[-1].text))
    graph = supervisor(records_task, model=delegates_each_turn)
    say(graph, "anything by Miles Davis?")
    say(graph, "the second one")

    assert seen == [
        "recommend\n\nRecent conversation, for context only:\nCustomer: anything by Miles Davis?",
        "recommend\n\nRecent conversation, for context only:\nCustomer: anything by Miles Davis?\n"
        "Assistant: Which one?\nCustomer: the second one",
    ]


def live_graph():
    return team.build_supervisor(checkpointer=InMemorySaver())


def calls(result, name):
    return [c["args"] for m in result["messages"] for c in (getattr(m, "tool_calls", None) or [])
            if c["name"] == name]


@pytest.mark.live
@live
def test_live_what_should_i_finish():
    answer = say(live_graph(), "What should I finish?", thread="live-finish")["messages"][-1].text

    assert "In Step" in answer and in_step_price() in answer


@pytest.mark.live
@live
def test_live_a_squashed_artist_name_resolves():
    agent = team.build_subagent(team.spec_named("music_recommendation"))
    result = agent.invoke({"messages": [{"role": "user", "content": "anything by acdc?"}]},
                          context=CustomerContext(customer_id=48))

    assert calls(result, "recommend_engine")[0].get("artist")
    assert "AC/DC" in result["messages"][-1].text


@pytest.mark.live
@live
def test_live_new_customer_is_asked_then_recommended(monkeypatch):
    monkeypatch.setattr(catalog, "get_library", lambda customer_id: [])
    graph = live_graph()

    first = say(graph, "Recommend me something.", thread="live-new")["messages"][-1].text
    assert "apple" in first.lower()
    second = say(graph, "An Android phone.", thread="live-new")["messages"][-1].text
    assert "music" in second.lower() or "genre" in second.lower()
    say(graph, "Jazz, please.", thread="live-new")

    assert store.get_preferences(48)["device"] == "other"
    assert store.get_preferences(48)["genres"] == ["Jazz"]


@pytest.mark.live
@live
def test_live_yes_buy_it_records_the_order():
    graph = live_graph()
    say(graph, "What am I closest to finishing?", thread="live-buy")
    done = say(graph, "Yes, buy it.", thread="live-buy")

    assert "__interrupt__" not in done
    assert [(o["album_id"], o["amount"]) for o in orders()] == [(205, in_step_price())]
    assert in_step_price() in done["messages"][-1].text

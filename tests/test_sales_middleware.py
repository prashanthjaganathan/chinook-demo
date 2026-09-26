from types import SimpleNamespace

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from chinook.agent.middleware import MustUseATool, PriceGuard
from chinook.foundation import config

OFFER = ToolMessage('{"final_price": "4.75", "list_price": "5.94"}', tool_call_id="c1")


def request(*messages):
    return SimpleNamespace(messages=list(messages), override=lambda **changes: changes)


def guard(*messages):
    return PriceGuard().after_model({"messages": list(messages)}, None)


def test_only_the_first_model_call_is_forced_to_use_a_tool():
    first = request(HumanMessage("what should I finish?"))
    later = request(HumanMessage("what should I finish?"), OFFER)

    assert MustUseATool.forced(first) == {"tool_choice": "any"}
    assert MustUseATool.forced(later) is later


def test_sourced_prices_pass_and_whole_dollars_match_cents():
    assert guard(OFFER, AIMessage("The other tracks are $4.75, down from $5.94.")) is None
    assert guard(ToolMessage('{"amount": "5.00"}', tool_call_id="c2"), AIMessage("That is $5.")) is None


def test_tool_calls_and_price_free_answers_pass():
    assert guard(AIMessage("", tool_calls=[{"name": "x", "args": {}, "id": "c9"}])) is None
    assert guard(OFFER, AIMessage("Which album?")) is None


def test_an_unsourced_price_retries_once_then_falls_back():
    made_up = AIMessage("Only $3.99!", id="a1")

    retry = guard(OFFER, made_up)
    assert retry["jump_to"] == "model" and retry["messages"][0].text == config.PRICE_RETRY

    fallback = guard(OFFER, HumanMessage(config.PRICE_RETRY), made_up)
    assert fallback["messages"][0].text == config.PRICE_FALLBACK
    assert fallback["messages"][0].id == "a1" and "jump_to" not in fallback

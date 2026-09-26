from types import SimpleNamespace

from langchain_core.messages import HumanMessage, ToolMessage

from chinook.agent.middleware import MustUseATool

OFFER = ToolMessage('{"final_price": "4.75", "list_price": "5.94"}', tool_call_id="c1")


def request(*messages):
    return SimpleNamespace(messages=list(messages), override=lambda **changes: changes)


def test_only_the_first_model_call_is_forced_to_use_a_tool():
    first = request(HumanMessage("what should I finish?"))
    later = request(HumanMessage("what should I finish?"), OFFER)

    assert MustUseATool.forced(first) == {"tool_choice": "any"}
    assert MustUseATool.forced(later) is later

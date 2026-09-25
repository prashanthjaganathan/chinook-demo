import os

import pytest

from chinook_agent import agent
from chinook_agent.context import CustomerContext


@pytest.fixture
def fake_keys(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")


def test_agent_builds_with_the_fallback_chain(fake_keys):
    graph = agent.build_agent()

    assert graph is not None


def test_agent_wires_every_tool_into_the_graph(fake_keys):
    from chinook_agent.tools import TOOLS

    nodes = agent.build_agent().get_graph().nodes

    assert "tools" in nodes
    assert len(TOOLS) == 4


@pytest.mark.live
@pytest.mark.skipif(not os.getenv("OPENAI_API_KEY"), reason="needs a real key")
def test_agent_answers_what_do_i_own():
    result = agent.build_agent().invoke(
        {"messages": [{"role": "user", "content": "How many tracks do I own?"}]},
        context=CustomerContext(customer_id=54),
    )

    # .text flattens the block list the Responses API returns.
    assert "38" in result["messages"][-1].text


@pytest.mark.live
def test_agent_offers_missing_tracks_with_discounted_price():
    result = agent.build_agent().invoke(
        {"messages": [{"role": "user", "content": "What album am I closest to finishing, and what would the rest cost?"}]},
        context=CustomerContext(customer_id=48),
    )
    answer = result["messages"][-1].text

    assert "In Step" in answer
    assert "4.75" in answer

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


def test_agent_exposes_the_tools(fake_keys):
    from chinook_agent.tools import TOOLS

    assert [tool.name for tool in TOOLS] == ["get_my_library"]


@pytest.mark.live
@pytest.mark.skipif(not os.getenv("OPENAI_API_KEY"), reason="needs a real key")
def test_agent_answers_what_do_i_own():
    result = agent.build_agent().invoke(
        {"messages": [{"role": "user", "content": "How many tracks do I own?"}]},
        context=CustomerContext(customer_id=54),
    )

    assert "38" in result["messages"][-1].content

import asyncio
import os
import sqlite3

import pytest
from helpers import FakeModel, call, once_then, refund_call, tool_results
from langchain.agents import create_agent
from langchain.agents.middleware import ModelFallbackMiddleware, ModelRetryMiddleware
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from chinook.agent import models, team
from chinook.agent.middleware import (
    SessionGuard,
    atool_error,
    model_failure,
    tool_error,
)
from chinook.agent.tools import find_purchases
from chinook.foundation import config
from chinook.foundation.context import CustomerContext
from chinook.helpers import store


class Request:
    def __init__(self, customer_id):
        self.runtime = type("R", (), {"context": CustomerContext(customer_id=customer_id)})()
        self.tool_call = {"name": "find_purchases", "id": "c1", "args": {}}


def names(stack):
    return [type(item).__name__ for item in stack]


def test_session_guard_stops_a_tool_without_identity():
    ran = []
    for bad in (None, 999999, True):
        message = SessionGuard().wrap_tool_call(Request(bad), lambda r: ran.append(r))
        assert message.status == "error" and message.content == config.NO_IDENTITY
    assert ran == []
    assert SessionGuard().wrap_tool_call(Request(54), lambda r: "ran") == "ran"


def test_the_async_session_guard_refuses_too():
    async def handler(request):
        return "ran"

    assert asyncio.run(SessionGuard().awrap_tool_call(Request(None), handler)).status == "error"


def test_a_resumed_write_is_rechecked_against_the_current_identity():
    agent = team.build_subagent(team.spec_named("invoice_support"), model=once_then(refund_call()),
                                  checkpointer=InMemorySaver())
    cfg = {"configurable": {"thread_id": "t1"}}
    agent.invoke({"messages": [{"role": "user", "content": "refund"}]}, config=cfg,
                 context=CustomerContext(customer_id=54))
    agent.invoke(Command(resume={"decisions": [{"type": "approve"}]}), config=cfg,
                 context=CustomerContext(customer_id=4))

    assert store.open_requests(54) == [] and store.open_requests(4) == []


def test_permission_errors_are_never_softened():
    assert tool_error(PermissionError("not yours")) is None
    assert tool_error(OSError("disk")) == tool_error(sqlite3.OperationalError("locked")) == config.DATA_UNAVAILABLE
    assert tool_error(ValueError("bad id")) == config.BAD_REQUEST
    assert tool_error(RuntimeError("new")) is None
    assert asyncio.run(atool_error(PermissionError())) is None


def test_error_messages_leak_no_internals():
    for text in (config.DATA_UNAVAILABLE, config.BAD_REQUEST, model_failure(RuntimeError("sk-abc at /Users/x/chinook.db"))):
        for secret in ("sk-abc", "/Users", "chinook.db", "Traceback", "SELECT"):
            assert secret not in text


def test_a_failing_tool_reaches_the_model_marked_as_an_error(monkeypatch):
    monkeypatch.setattr("chinook.helpers.catalog.customer_purchases",
                        lambda *a: (_ for _ in ()).throw(sqlite3.OperationalError("locked")))
    result = team.build_subagent(team.spec_named("invoice_support"),
                                   model=once_then(call("find_purchases"))).invoke(
        {"messages": [{"role": "user", "content": "go"}]}, context=CustomerContext(customer_id=54))
    message = tool_results(result["messages"])[0]

    assert message.status == "error" and message.content == config.DATA_UNAVAILABLE


def test_middleware_order_is_guard_then_errors_and_retry_then_fallback():
    spares = [once_then(AIMessage("spare"))]
    sub = names(team.subagent_middleware(team.spec_named("invoice_support"), spares))
    sup = names(team.supervisor_middleware(spares=spares))

    assert sub.index("SessionGuard") < sub.index("ToolErrorMiddleware")
    for stack in (sub, sup):
        assert stack.index("ModelRetryMiddleware") < stack.index("ModelFallbackMiddleware")
    assert sup[0] == "AuthMiddleware" and sub[-1] == "HumanInTheLoopMiddleware"


def test_a_runaway_subagent_stops_with_a_message():
    looping = FakeModel(respond=lambda m: call("find_purchases", call_id=f"c{len(m)}"))
    result = team.build_subagent(team.spec_named("invoice_support"), model=looping).invoke(
        {"messages": [{"role": "user", "content": "go"}]}, context=CustomerContext(customer_id=54))

    assert len(tool_results(result["messages"])) <= config.SUBAGENT_TOOL_CALLS_PER_RUN
    assert "limit" in result["messages"][-1].text.lower()


def test_a_runaway_supervisor_stops_with_a_message():
    looping = FakeModel(respond=lambda m: call("ask_music_recommendation", {"task": "go"}, f"c{len(m)}"))
    result = team.build_supervisor(model=looping, subagent_model=once_then(AIMessage("ok"))).invoke(
        {"messages": [{"role": "user", "content": "go"}]}, context=CustomerContext(customer_id=54))

    assert "limit" in result["messages"][-1].text.lower()


def test_parallel_calls_past_the_limit_do_not_crash():
    both = FakeModel(respond=lambda m: AIMessage("", tool_calls=[
        {"name": "find_purchases", "args": {}, "id": f"a{len(m)}"},
        {"name": "search_catalog", "args": {}, "id": f"b{len(m)}"}]))
    result = team.build_subagent(team.spec_named("invoice_support"), model=both).invoke(
        {"messages": [{"role": "user", "content": "go"}]}, context=CustomerContext(customer_id=54))

    assert result["messages"][-1].text


def failing(name):
    return FakeModel(respond=lambda m: (_ for _ in ()).throw(RuntimeError(f"{name} is down")))


def run(primary, *spares):
    graph = create_agent(model=primary, tools=[], middleware=[
        ModelRetryMiddleware(max_retries=1, initial_delay=0, on_failure=model_failure),
        ModelFallbackMiddleware(*spares)])
    return graph.invoke({"messages": [{"role": "user", "content": "hi"}]})["messages"][-1].text


def test_the_fallback_answers_when_the_primary_fails():
    assert run(failing("primary"), once_then(AIMessage("spare answered"))) == "spare answered"


def test_every_model_down_returns_the_safe_message():
    assert run(failing("primary"), failing("spare")) == config.MODEL_UNAVAILABLE


def test_worst_case_nested_turn_time_is_within_budget():
    assert config.worst_case_seconds() <= config.TURN_BUDGET_SECONDS


@pytest.mark.live
@pytest.mark.skipif(not os.getenv("OPENAI_API_KEY"), reason="needs a real key")
@pytest.mark.parametrize("spec", config.MODEL_CHAIN, ids=[s.name for s in config.MODEL_CHAIN])
def test_every_model_in_the_chain_accepts_the_real_tools(spec):
    reply = models.build(spec).bind_tools([find_purchases]).invoke("Which of my purchases is Midnight?")

    assert [c["name"] for c in reply.tool_calls] == ["find_purchases"]

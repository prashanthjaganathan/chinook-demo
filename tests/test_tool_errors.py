import sqlite3

import pytest
from langchain.agents import create_agent
from langchain.agents.middleware import ToolErrorMiddleware
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import tool

from chinook_agent import agent
from chinook_agent.middleware import (
    BAD_REQUEST,
    DATA_UNAVAILABLE,
    atool_error,
    tool_error,
)

BOOM = None


@tool
def flaky() -> str:
    """Raises whatever the test asks for."""
    raise BOOM


class CallingModel(BaseChatModel):
    @property
    def _llm_type(self) -> str:
        return "calling"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        done = any(getattr(item, "tool_call_id", None) for item in messages)
        message = (
            AIMessage(content="acknowledged")
            if done
            else AIMessage(content="", tool_calls=[{"name": "flaky", "args": {}, "id": "c1"}])
        )
        return ChatResult(generations=[ChatGeneration(message=message)])

    def bind_tools(self, tools, **kwargs):
        return self


def run_with(error):
    global BOOM
    BOOM = error
    graph = create_agent(
        model=CallingModel(),
        tools=[flaky],
        middleware=[ToolErrorMiddleware(tool_error, aon_error=atool_error)],
    )
    return graph.invoke({"messages": [{"role": "user", "content": "go"}]})


def test_permission_error_is_not_rewritten():
    assert tool_error(PermissionError("not your account")) is None


def test_a_plain_os_error_becomes_a_friendly_message():
    assert tool_error(OSError("disk on fire")) == DATA_UNAVAILABLE


def test_a_database_error_becomes_a_friendly_message():
    assert tool_error(sqlite3.OperationalError("database is locked")) == DATA_UNAVAILABLE


def test_a_value_error_becomes_a_friendly_message():
    assert tool_error(ValueError("customer_id must be a positive integer")) == BAD_REQUEST


def test_an_unknown_exception_propagates():
    assert tool_error(RuntimeError("something new")) is None


def test_the_order_of_the_checks_is_what_makes_it_fail_closed():
    # PermissionError is an OSError, so a naive isinstance(error, OSError) first
    # would smother it. This asserts the real ordering, not the naive one.
    assert issubclass(PermissionError, OSError)
    assert tool_error(PermissionError()) is None
    assert tool_error(OSError()) == DATA_UNAVAILABLE


def test_error_messages_leak_no_internals():
    leaky = sqlite3.OperationalError(
        "no such table: Customer in /Users/someone/data/chinook.db"
    )
    message = tool_error(leaky)

    for secret in ("/Users", "chinook.db", "no such table", "Customer", "Traceback"):
        assert secret not in message


def test_a_failing_tool_is_reported_to_the_model_as_an_error():
    result = run_with(sqlite3.OperationalError("database is locked"))
    tool_messages = [m for m in result["messages"] if getattr(m, "status", None)]

    assert tool_messages
    assert tool_messages[0].status == "error"
    assert tool_messages[0].content == DATA_UNAVAILABLE


def test_a_permission_error_stops_the_run_rather_than_answering():
    with pytest.raises(PermissionError):
        run_with(PermissionError("not your account"))


def test_identity_is_listed_before_tool_errors():
    names = [type(item).__name__ for item in agent.middleware_stack(spares=[])]

    assert names.index("IdentityMiddleware") < names.index("ToolErrorMiddleware")


def test_the_async_handler_agrees_with_the_sync_one():
    import asyncio

    for error in (PermissionError(), OSError(), ValueError(), RuntimeError()):
        assert tool_error(error) == asyncio.run(atool_error(error))


def test_an_unreachable_support_store_refuses_rather_than_crashing(monkeypatch):
    from chinook_agent.middleware import session_problem
    from chinook_agent.context import CustomerContext

    monkeypatch.setattr(
        "chinook_agent.middleware.thread_id", lambda: "t1"
    )
    monkeypatch.setattr(
        "chinook_agent.support_db.bind_thread",
        lambda *a, **k: (_ for _ in ()).throw(OSError("read-only file system")),
    )

    assert session_problem(CustomerContext(customer_id=54)) == DATA_UNAVAILABLE


def test_an_unreachable_catalog_refuses_rather_than_crashing(monkeypatch):
    from chinook_agent.middleware import identity_problem
    from chinook_agent.context import CustomerContext

    monkeypatch.setattr(
        "chinook_agent.db.customer_exists",
        lambda *a, **k: (_ for _ in ()).throw(sqlite3.OperationalError("locked")),
    )

    assert identity_problem(CustomerContext(customer_id=54)) == DATA_UNAVAILABLE


def test_a_store_outage_never_fails_open(monkeypatch):
    from chinook_agent.middleware import session_problem
    from chinook_agent.context import CustomerContext

    monkeypatch.setattr("chinook_agent.middleware.thread_id", lambda: "t1")
    monkeypatch.setattr(
        "chinook_agent.support_db.bind_thread",
        lambda *a, **k: (_ for _ in ()).throw(OSError("gone")),
    )

    assert session_problem(CustomerContext(customer_id=54)) is not None

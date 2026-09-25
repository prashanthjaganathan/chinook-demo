import asyncio

import pytest
from langchain.agents import create_agent
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from chinook_agent import support_db
from chinook_agent.agent import APPROVAL
from chinook_agent.context import CustomerContext
from chinook_agent.middleware import (
    NO_IDENTITY,
    WRONG_OWNER,
    IdentityMiddleware,
    session_problem,
)
from chinook_agent.tools import TOOLS

OWNER = 54
INTRUDER = 4
PROTECTED_TRACK = 1504
TOOL_RUNS = []


@pytest.fixture(autouse=True)
def scratch_db(tmp_path, monkeypatch):
    monkeypatch.setenv("SUPPORT_DB", str(tmp_path / "support.sqlite"))
    TOOL_RUNS.clear()


class RefundingModel(BaseChatModel):
    @property
    def _llm_type(self) -> str:
        return "refunding"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        done = any(getattr(item, "tool_call_id", None) for item in messages)
        message = (
            AIMessage(content="Done.")
            if done
            else AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "request_refund_or_swap",
                        "args": {
                            "track_id": PROTECTED_TRACK,
                            "action": "refund",
                            "reason": "will not play",
                        },
                        "id": "call-1",
                    }
                ],
            )
        )
        return ChatResult(generations=[ChatGeneration(message=message)])

    def bind_tools(self, tools, **kwargs):
        return self


def graph():
    return create_agent(
        model=RefundingModel(),
        tools=TOOLS,
        middleware=[IdentityMiddleware(), APPROVAL],
        context_schema=CustomerContext,
        checkpointer=InMemorySaver(),
    )


def start(agent, customer_id=OWNER, thread="t1"):
    config = {"configurable": {"thread_id": thread}}
    result = agent.invoke(
        {"messages": [{"role": "user", "content": "Refund it."}]},
        config=config,
        context=CustomerContext(customer_id=customer_id),
    )
    return result, config


def test_a_tool_call_without_identity_is_refused():
    assert session_problem(CustomerContext(customer_id=None)) == NO_IDENTITY


def test_a_tool_call_from_an_unknown_customer_is_refused():
    assert session_problem(CustomerContext(customer_id=999999)) == NO_IDENTITY


def test_a_thread_keeps_the_customer_that_opened_it():
    agent = graph()
    start(agent, OWNER)

    assert support_db.bind_thread("t1", INTRUDER) == OWNER


def test_a_tool_refuses_when_the_context_is_not_the_thread_owner():
    agent = graph()
    start(agent, OWNER)

    result = agent.invoke(
        {"messages": [{"role": "user", "content": "Refund it."}]},
        config={"configurable": {"thread_id": "t1"}},
        context=CustomerContext(customer_id=INTRUDER),
    )

    assert WRONG_OWNER in result["messages"][-1].text
    assert support_db.open_requests(INTRUDER) == []


def test_a_resumed_tool_call_is_rechecked_against_the_current_identity():
    agent = graph()
    _, config = start(agent, OWNER)

    agent.invoke(
        Command(resume={"decisions": [{"type": "approve"}]}),
        config=config,
        context=CustomerContext(customer_id=None),
    )

    assert support_db.open_requests(OWNER) == []


def test_a_resume_by_the_real_owner_still_works():
    agent = graph()
    _, config = start(agent, OWNER)

    agent.invoke(
        Command(resume={"decisions": [{"type": "approve"}]}),
        config=config,
        context=CustomerContext(customer_id=OWNER),
    )

    assert len(support_db.open_requests(OWNER)) == 1


def test_a_second_customer_gets_their_own_thread():
    agent = graph()
    start(agent, OWNER, thread="t1")
    start(agent, INTRUDER, thread="t2")

    assert support_db.bind_thread("t1", OWNER) == OWNER
    assert support_db.bind_thread("t2", INTRUDER) == INTRUDER


def test_binding_is_idempotent():
    assert support_db.bind_thread("t9", OWNER) == OWNER
    assert support_db.bind_thread("t9", OWNER) == OWNER


def test_only_one_customer_wins_a_racing_thread_claim():
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=8) as pool:
        owners = set(pool.map(lambda c: support_db.bind_thread("race", c), range(1, 9)))

    assert len(owners) == 1


def test_the_async_hook_agrees_with_the_sync_one():
    middleware = IdentityMiddleware()
    assert hasattr(middleware, "awrap_tool_call")

    for customer_id in (None, 999999, OWNER):
        context = CustomerContext(customer_id=customer_id)
        assert session_problem(context) == asyncio.run(
            asyncio.to_thread(session_problem, context)
        )


class Request:
    """Minimal stand-in so the tool hook can be exercised on its own."""

    def __init__(self, customer_id):
        self.runtime = type("R", (), {"context": CustomerContext(customer_id=customer_id)})()
        self.tool_call = {"name": "get_my_library", "id": "call-1", "args": {}}


def test_the_tool_hook_refuses_on_its_own():
    # before_agent catches these first in the assembled graph, so the hook is a
    # second boundary rather than the only one. Exercised directly here.
    middleware = IdentityMiddleware()
    ran = []

    for customer_id, expected in ((None, NO_IDENTITY), (999999, NO_IDENTITY)):
        message = middleware.wrap_tool_call(
            Request(customer_id), lambda request: ran.append(request) or "ran"
        )

        assert message.status == "error"
        assert message.content == expected

    assert ran == []


def test_the_tool_hook_lets_a_real_customer_through():
    middleware = IdentityMiddleware()

    assert middleware.wrap_tool_call(Request(OWNER), lambda request: "ran") == "ran"


def test_the_async_tool_hook_refuses_too():
    middleware = IdentityMiddleware()

    async def handler(request):
        return "ran"

    message = asyncio.run(middleware.awrap_tool_call(Request(None), handler))

    assert message.status == "error"
    assert message.content == NO_IDENTITY

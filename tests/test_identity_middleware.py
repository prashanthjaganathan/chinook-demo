import asyncio

import pytest
from langchain.agents import create_agent
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from chinook_agent.context import CustomerContext
from chinook_agent.middleware import NO_IDENTITY, IdentityMiddleware, identity_problem
from chinook_agent.tools import TOOLS

BAD_IDENTITIES = (None, 0, -1, True, "2", 2.0, 2**63, 999999, [1])


class Runtime:
    def __init__(self, context):
        self.context = context


MODEL_CALLS = []


class CountingModel(BaseChatModel):
    @property
    def _llm_type(self) -> str:
        return "counting"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        MODEL_CALLS.append(1)
        return ChatResult(generations=[ChatGeneration(message=AIMessage("reached"))])

    def bind_tools(self, tools, **kwargs):
        return self


def run_with(customer_id):
    MODEL_CALLS.clear()
    graph = create_agent(
        model=CountingModel(),
        tools=TOOLS,
        middleware=[IdentityMiddleware()],
        context_schema=CustomerContext,
    )
    result = graph.invoke(
        {"messages": [{"role": "user", "content": "show me my invoices"}]},
        context=CustomerContext(customer_id=customer_id),
    )
    return result["messages"][-1].text, len(MODEL_CALLS)


@pytest.mark.parametrize("customer_id", BAD_IDENTITIES)
def test_before_agent_refuses_every_bad_identity(customer_id):
    assert identity_problem(CustomerContext(customer_id=customer_id)) == NO_IDENTITY


def test_a_missing_context_is_refused():
    assert identity_problem(None) == NO_IDENTITY


def test_a_real_customer_continues():
    assert identity_problem(CustomerContext(customer_id=54)) is None


def test_every_real_customer_is_accepted():
    assert all(
        identity_problem(CustomerContext(customer_id=customer_id)) is None
        for customer_id in range(1, 60)
    )


@pytest.mark.parametrize("customer_id", [None, 0, True, "2", 999999])
def test_a_refused_run_never_reaches_the_model(customer_id):
    answer, model_calls = run_with(customer_id)

    assert answer == NO_IDENTITY
    assert model_calls == 0


def test_a_valid_run_reaches_the_model():
    answer, model_calls = run_with(54)

    assert answer == "reached"
    assert model_calls == 1


def test_an_unknown_customer_is_indistinguishable_from_a_malformed_one():
    assert identity_problem(CustomerContext(customer_id=999999)) == identity_problem(
        CustomerContext(customer_id="nonsense")
    )


def test_the_refusal_names_no_customer():
    assert "999999" not in NO_IDENTITY
    assert "customer_id" not in NO_IDENTITY


def test_the_async_hook_agrees_with_the_sync_one():
    middleware = IdentityMiddleware()
    for customer_id in (None, 0, "2", 999999, 54):
        context = Runtime(CustomerContext(customer_id=customer_id))
        sync = middleware.before_agent({}, context)
        alternative = asyncio.run(middleware.abefore_agent({}, context))

        assert (sync is None) == (alternative is None)
        if sync is not None:
            assert sync["jump_to"] == alternative["jump_to"] == "end"


def test_identity_runs_before_every_other_middleware():
    from chinook_agent import agent

    names = [type(item).__name__ for item in agent.middleware_stack(spares=[])]

    assert names[0] == "IdentityMiddleware"


def test_the_stack_keeps_its_order_with_fallbacks_present():
    from chinook_agent import agent

    spares = [CountingModel(), CountingModel()]
    names = [type(item).__name__ for item in agent.middleware_stack(spares=spares)]

    assert names == [
        "IdentityMiddleware",
        "ToolErrorMiddleware",
        "ModelCallLimitMiddleware",
        "ToolCallLimitMiddleware",
        "ModelRetryMiddleware",
        "ModelFallbackMiddleware",
        "HumanInTheLoopMiddleware",
    ]

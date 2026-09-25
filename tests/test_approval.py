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
from chinook_agent.tools import TOOLS

CUSTOMER = 54
PROTECTED_TRACK = 1504


@pytest.fixture(autouse=True)
def scratch_db(tmp_path, monkeypatch):
    monkeypatch.setenv("SUPPORT_DB", str(tmp_path / "support.sqlite"))


class ScriptedModel(BaseChatModel):
    """Asks for a refund once, then answers."""

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        already_called = any(getattr(m, "tool_call_id", None) for m in messages)
        message = (
            AIMessage(content="Done.")
            if already_called
            else AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "request_refund_or_swap",
                        "args": {
                            "track_id": PROTECTED_TRACK,
                            "action": "refund",
                            "reason": "will not play on Android",
                        },
                        "id": "call-1",
                    }
                ],
            )
        )
        return ChatResult(generations=[ChatGeneration(message=message)])

    def bind_tools(self, tools, **kwargs):
        return self


def scripted_agent():
    return create_agent(
        model=ScriptedModel(),
        tools=TOOLS,
        middleware=[APPROVAL],
        context_schema=CustomerContext,
        checkpointer=InMemorySaver(),
    )


CONTEXT = CustomerContext(customer_id=CUSTOMER)


def resume(graph, config, decision):
    # Context is not carried across the interrupt, so it has to be sent again.
    return graph.invoke(
        Command(resume={"decisions": [{"type": decision}]}), config=config, context=CONTEXT
    )


def start(graph, thread="t1"):
    config = {"configurable": {"thread_id": thread}}
    result = graph.invoke(
        {"messages": [{"role": "user", "content": "Refund it please."}]},
        config=config,
        context=CustomerContext(customer_id=CUSTOMER),
    )
    return result, config


def test_the_run_pauses_before_writing():
    result, _ = start(scripted_agent())

    assert "__interrupt__" in result
    assert support_db.open_requests(CUSTOMER) == []


def test_approve_writes_exactly_one_request():
    graph = scripted_agent()
    _, config = start(graph)

    resume(graph, config, "approve")

    assert len(support_db.open_requests(CUSTOMER)) == 1


def test_reject_writes_nothing():
    graph = scripted_agent()
    _, config = start(graph)

    resume(graph, config, "reject")

    assert support_db.open_requests(CUSTOMER) == []


def test_approval_allows_only_approve_and_reject():
    config = APPROVAL.interrupt_on["request_refund_or_swap"]
    decisions = getattr(config, "allowed_decisions", None) or config["allowed_decisions"]

    assert set(decisions) == {"approve", "reject"}


def test_only_the_write_tool_is_gated():
    assert set(APPROVAL.interrupt_on) == {"request_refund_or_swap"}
    assert len(TOOLS) == 5


@pytest.mark.parametrize("bad", ["", {"decisions": "approve"}])
def test_a_malformed_resume_breaks_the_thread_for_good(bad):
    # Known LangChain behaviour: the bad payload lands in the checkpoint and every
    # later resume replays it. Approvals must never come from a hand-typed box.
    graph = scripted_agent()
    _, config = start(graph)

    with pytest.raises(Exception):
        graph.invoke(Command(resume=bad), config=config, context=CONTEXT)
    with pytest.raises(Exception):
        resume(graph, config, "approve")

    assert support_db.open_requests(CUSTOMER) == []


def test_an_empty_decision_list_is_survivable():
    graph = scripted_agent()
    _, config = start(graph)

    graph.invoke(Command(resume={}), config=config, context=CONTEXT)
    resume(graph, config, "approve")

    assert len(support_db.open_requests(CUSTOMER)) == 1


def test_the_safe_decision_helper_only_emits_valid_payloads():
    from approve import payload

    assert payload("approve") == {"decisions": [{"type": "approve"}]}
    assert payload("reject") == {"decisions": [{"type": "reject"}]}
    with pytest.raises(ValueError):
        payload("maybe")


def test_a_resume_without_identity_refuses_instead_of_crashing():
    graph = scripted_agent()
    _, config = start(graph)

    graph.invoke(Command(resume={"decisions": [{"type": "approve"}]}), config=config)

    assert support_db.open_requests(CUSTOMER) == []

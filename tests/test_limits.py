from langchain.agents import create_agent
from langchain.agents.middleware import ModelCallLimitMiddleware, ToolCallLimitMiddleware
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import tool
from langgraph.checkpoint.memory import InMemorySaver

from chinook_agent import agent, config

TOOL_RUNS = []


@tool
def spin() -> str:
    """Always succeeds, so only a limit can stop the loop."""
    TOOL_RUNS.append(1)
    return "again"


@tool
def other() -> str:
    """A second tool, so parallel calls can be exercised."""
    TOOL_RUNS.append(1)
    return "other"


class LoopingModel(BaseChatModel):
    """Never stops asking for tools, which is the failure the limits exist for."""

    @property
    def _llm_type(self) -> str:
        return "looping"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        return ChatResult(
            generations=[
                ChatGeneration(
                    message=AIMessage(
                        content="",
                        tool_calls=[
                            {"name": "spin", "args": {}, "id": f"c{len(messages)}"}
                        ],
                    )
                )
            ]
        )

    def bind_tools(self, tools, **kwargs):
        return self


class ParallelModel(LoopingModel):
    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        return ChatResult(
            generations=[
                ChatGeneration(
                    message=AIMessage(
                        content="",
                        tool_calls=[
                            {"name": "spin", "args": {}, "id": f"a{len(messages)}"},
                            {"name": "other", "args": {}, "id": f"b{len(messages)}"},
                        ],
                    )
                )
            ]
        )


def run(model, middleware):
    TOOL_RUNS.clear()
    graph = create_agent(
        model=model,
        tools=[spin, other],
        middleware=middleware,
        checkpointer=InMemorySaver(),
    )
    return graph.invoke(
        {"messages": [{"role": "user", "content": "go"}]},
        config={"configurable": {"thread_id": "t1"}},
    )


def test_a_runaway_tool_loop_stops_at_the_limit():
    result = run(
        LoopingModel(),
        [ToolCallLimitMiddleware(run_limit=3, exit_behavior="end")],
    )

    assert len(TOOL_RUNS) == 3
    assert "limit" in result["messages"][-1].text.lower()


def test_a_runaway_model_loop_stops_at_the_limit():
    result = run(
        LoopingModel(),
        [ModelCallLimitMiddleware(run_limit=3, exit_behavior="end")],
    )

    assert "limit" in result["messages"][-1].text.lower()


def test_the_limit_ends_with_a_customer_facing_message():
    result = run(
        LoopingModel(),
        [ToolCallLimitMiddleware(run_limit=2, exit_behavior="end")],
    )
    answer = result["messages"][-1].text

    assert answer
    assert "Traceback" not in answer


def test_a_global_limit_does_not_crash_on_parallel_calls():
    result = run(
        ParallelModel(),
        [ToolCallLimitMiddleware(run_limit=1, exit_behavior="end")],
    )

    assert result["messages"][-1].text


def test_both_limits_together_stop_a_loop():
    result = run(
        LoopingModel(),
        [
            ModelCallLimitMiddleware(run_limit=4, exit_behavior="end"),
            ToolCallLimitMiddleware(run_limit=4, exit_behavior="end"),
        ],
    )

    assert len(TOOL_RUNS) <= 4
    assert result["messages"][-1].text


def test_the_configured_limits_are_in_the_stack():
    names = [type(item).__name__ for item in agent.middleware_stack(spares=[])]

    assert "ModelCallLimitMiddleware" in names
    assert "ToolCallLimitMiddleware" in names
    assert names.index("IdentityMiddleware") < names.index("ModelCallLimitMiddleware")


def test_the_limits_leave_room_for_a_real_conversation():
    # The longest live flow so far used four tool calls in one turn.
    assert config.TOOL_CALLS_PER_RUN >= 12
    assert config.MODEL_CALLS_PER_RUN >= 8
    assert config.TOOL_CALLS_PER_THREAD > config.TOOL_CALLS_PER_RUN
    assert config.MODEL_CALLS_PER_THREAD > config.MODEL_CALLS_PER_RUN

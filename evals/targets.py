"""How each eval runs the agent: real prompts and middleware, a scratch store, nothing written for real."""
import os
import tempfile
import uuid
from functools import cache
from pathlib import Path

os.environ["SUPPORT_DB"] = str(Path(tempfile.mkdtemp(prefix="chinook_eval_")) / "support.sqlite")

from langchain_core.messages import AIMessage, ToolMessage  # noqa: E402
from langgraph.checkpoint.memory import InMemorySaver  # noqa: E402

from chinook.agent.team import (  # noqa: E402
    build_subagent,
    build_supervisor,
    spec_named,
)
from chinook.foundation.context import CustomerContext  # noqa: E402


def summarize(messages) -> dict:
    ai = [m for m in messages if isinstance(m, AIMessage)]
    return {
        "calls": [{"name": call["name"], "args": call["args"]} for m in ai for call in m.tool_calls],
        "reply": next((m.text for m in reversed(ai) if not m.tool_calls), ""),
        "tool_text": "\n".join(m.text for m in messages if isinstance(m, ToolMessage)),
    }


@cache
def supervisor():
    return build_supervisor(checkpointer=InMemorySaver())


@cache
def subagent(name: str):
    return build_subagent(spec_named(name), checkpointer=InMemorySaver())


def run(agent, inputs: dict, **kwargs) -> dict:
    config = {"configurable": {"thread_id": str(uuid.uuid4())}}
    context = CustomerContext(customer_id=inputs["customer_id"])
    agent.invoke({"messages": [{"role": "user", "content": inputs["message"]}]},
                 config=config, context=context, **kwargs)
    # Read the saved state: a run paused for approval still holds the call it proposed.
    return summarize(agent.get_state(config).values["messages"])


def supervisor_turn(inputs: dict) -> dict:
    return run(supervisor(), inputs)


def sales_first_decision(inputs: dict) -> dict:
    return run(subagent("music_recommendation"), inputs, interrupt_before=["tools"])


def support_until_pause(inputs: dict) -> dict:
    return run(subagent("invoice_support"), inputs)

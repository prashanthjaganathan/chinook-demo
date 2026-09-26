from typing import Any

from langchain.tools import ToolRuntime
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from chinook import refunds
from chinook.context import CustomerContext


def runtime_for(customer_id, thread="t1", call="c1", state=None):
    return ToolRuntime(
        state=state or {},
        context=CustomerContext(customer_id=customer_id),
        config={"configurable": {"thread_id": thread}},
        stream_writer=lambda *args, **kwargs: None,
        tool_call_id=call,
        store=None,
    )


def ref(customer_id=54, track="midnight"):
    return refunds.find(customer_id, track=track)["purchases"][0]["purchase_ref"]


def refund_call(reason="wont_play", **args):
    return call("request_refund", {"purchase_ref": ref(), "reason": reason, "device": "other", **args})


def call(name, args=None, call_id="call-1"):
    return AIMessage(content="", tool_calls=[{"name": name, "args": args or {}, "id": call_id}])


def tool_results(messages):
    return [m for m in messages if getattr(m, "tool_call_id", None)]


class FakeModel(BaseChatModel):
    """Replies with respond(messages); lets agents run offline and deterministically."""

    respond: Any

    @property
    def _llm_type(self) -> str:
        return "fake"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        return ChatResult(generations=[ChatGeneration(message=self.respond(messages))])

    def bind_tools(self, tools, **kwargs):
        return self


def once_then(first: AIMessage, then: str = "done") -> FakeModel:
    """Calls a tool once, then answers with `then` after the tool result comes back."""
    return FakeModel(respond=lambda messages: AIMessage(then) if tool_results(messages) else first)

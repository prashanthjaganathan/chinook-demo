import asyncio
import sqlite3
from typing import NotRequired

import langchain.agents.middleware.human_in_the_loop as hitl
from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware, hook_config
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.config import get_config
from langgraph.types import interrupt
from pydantic import BaseModel

from chinook.agent import models
from chinook.domain import auth
from chinook.foundation import config
from chinook.helpers import catalog, otp, store


def thread_id() -> str | None:
    try:
        return get_config().get("configurable", {}).get("thread_id")
    except Exception:
        return None


def session_problem(customer_id) -> str | None:
    """The id must be a real customer, and must match whoever opened this thread."""
    try:
        catalog.valid_id(customer_id, "customer_id")
        if not catalog.customer_exists(customer_id):
            return config.NO_IDENTITY
        thread = thread_id()
        if thread and store.bind_thread(thread, customer_id) != customer_id:
            return config.WRONG_OWNER
    except ValueError:
        return config.NO_IDENTITY
    except (sqlite3.Error, OSError):
        # Ownership cannot be confirmed, so refuse rather than assume it is fine.
        return config.DATA_UNAVAILABLE
    return None


def refuse(text: str) -> dict:
    return {"messages": [AIMessage(text)], "jump_to": "end"}


class PhoneGuess(BaseModel):
    digits: str | None = None


def llm_phone(text: str) -> str | None:
    # Not an agent call, so the middleware chain does not cover it; fall back explicitly.
    chain = [models.build(spec).with_structured_output(PhoneGuess) for spec in config.MODEL_CHAIN]
    guess = chain[0].with_fallbacks(chain[1:]).invoke(
        f"Return the phone number in this message as digits only, or nothing:\n{text}")
    return guess.digits


class AuthState(AgentState):
    auth_stage: NotRequired[str | None]
    auth_attempts: NotRequired[int]
    pending_question: NotRequired[str | None]
    pending_phone: NotRequired[str | None]
    pending_customer_id: NotRequired[int | None]
    verified_customer_id: NotRequired[int | None]


class AuthMiddleware(AgentMiddleware):
    """The only writer of verified_customer_id. Nothing below it runs until identity is settled."""

    state_schema = AuthState

    def __init__(self, llm_fallback=llm_phone):
        super().__init__()
        self.llm_fallback = llm_fallback

    @hook_config(can_jump_to=["end"])
    def before_agent(self, state, runtime) -> dict | None:
        known = getattr(runtime.context, "customer_id", None)
        if known is None:
            known = state.get("verified_customer_id")
        if known is not None:
            problem = session_problem(known)
            return refuse(problem) if problem else None

        text = next((m.text for m in reversed(state["messages"]) if isinstance(m, HumanMessage)), "")
        decision = auth.next_step(
            state, text, catalog.customer_by_phone,
            extract=lambda message: auth.extract_phone(message, self.llm_fallback))
        if decision.send_code_to:
            otp.send_code(decision.send_code_to)
        if decision.verified is None:
            return {**refuse(decision.reply), **decision.updates}

        problem = session_problem(decision.verified)
        if problem:
            return refuse(problem)
        # Replay the question asked before login so the customer never repeats it.
        return {**decision.updates, "pending_question": None,
                "messages": [AIMessage(config.AUTHENTICATED), HumanMessage(state["pending_question"])]}

    @hook_config(can_jump_to=["end"])
    async def abefore_agent(self, state, runtime) -> dict | None:
        return await asyncio.to_thread(self.before_agent, state, runtime)


class SessionGuard(AgentMiddleware):
    """Re-checks the customer before every subagent tool call, including after an approval resume."""

    def wrap_tool_call(self, request, handler):
        problem = session_problem(getattr(request.runtime.context, "customer_id", None))
        return refused_call(request, problem) if problem else handler(request)

    async def awrap_tool_call(self, request, handler):
        customer_id = getattr(request.runtime.context, "customer_id", None)
        problem = await asyncio.to_thread(session_problem, customer_id)
        return refused_call(request, problem) if problem else await handler(request)


class MustUseATool(AgentMiddleware):
    """The first model call in a run must call a tool, so answers come from the engine."""

    @staticmethod
    def forced(request):
        started = any(isinstance(m, ToolMessage) for m in request.messages)
        # Any tool, not a specific one: "yes, buy it" must be free to reach buy_completion.
        return request if started else request.override(tool_choice="any")

    def wrap_model_call(self, request, handler):
        return handler(self.forced(request))

    async def awrap_model_call(self, request, handler):
        return await handler(self.forced(request))


APPROVE_WORDS = {"approve", "approved", "yes", "y", "ok"}


def plain_word_interrupt(request):
    """Studio's resume box can send a bare word; any word but an approve word rejects."""
    answer = interrupt(request)
    if not isinstance(answer, str):
        return answer
    kind = "approve" if answer.strip().strip('"').lower() in APPROVE_WORDS else "reject"
    return {"decisions": [{"type": kind}] * len(request["action_requests"])}


# HumanInTheLoopMiddleware reads the resume through this module-level name.
hitl.interrupt = plain_word_interrupt


def refused_call(request, text: str) -> ToolMessage:
    return ToolMessage(content=text, name=request.tool_call["name"],
                       tool_call_id=request.tool_call["id"], status="error")


def tool_error(error: Exception, request=None) -> str | None:
    """None re-raises. PermissionError subclasses OSError, so it is checked first."""
    if isinstance(error, PermissionError):
        return None
    if isinstance(error, (sqlite3.Error, OSError)):
        return config.DATA_UNAVAILABLE
    if isinstance(error, ValueError):
        return config.BAD_REQUEST
    return None


async def atool_error(error: Exception, request=None) -> str | None:
    return tool_error(error)


def model_failure(error: Exception) -> str:
    # The provider's own error text can carry keys and endpoints, so it is never repeated.
    return config.MODEL_UNAVAILABLE

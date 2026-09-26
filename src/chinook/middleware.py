import asyncio
import sqlite3
from typing import NotRequired

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware, hook_config
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.config import get_config
from pydantic import BaseModel

from chinook import auth, catalog, config, models, otp, store


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
    guess = models.primary().with_structured_output(PhoneGuess).invoke(
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

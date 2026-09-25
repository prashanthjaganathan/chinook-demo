import asyncio
import sqlite3

from langchain.agents.middleware import AgentMiddleware, hook_config
from langchain_core.messages import AIMessage, ToolMessage
from langgraph.config import get_config

from chinook_agent import db, support_db

# One message for every kind of bad identity, so customer ids cannot be probed.
NO_IDENTITY = (
    "I cannot see who is signed in, so I cannot look at any account. "
    "Please sign in and start again."
)
WRONG_OWNER = (
    "This conversation belongs to a different account. "
    "Please start a new one to continue."
)
DATA_UNAVAILABLE = (
    "I could not reach the store's records just now, so nothing was checked "
    "or changed. Please try again in a moment."
)
BAD_REQUEST = "That request was not valid, so nothing was changed."
MODEL_UNAVAILABLE = (
    "I could not reach the assistant service just now, so nothing was checked "
    "or changed. Please try again in a moment."
)


def model_failure(error: Exception) -> str:
    """Every model in the chain failed. The provider's own text is not repeated."""
    return MODEL_UNAVAILABLE


def identity_problem(context) -> str | None:
    customer_id = getattr(context, "customer_id", None)
    try:
        db.valid_id(customer_id, "customer_id")
    except ValueError:
        return NO_IDENTITY
    try:
        known = db.customer_exists(customer_id)
    except (sqlite3.Error, OSError):
        return DATA_UNAVAILABLE
    return None if known else NO_IDENTITY


def thread_id() -> str | None:
    try:
        return get_config().get("configurable", {}).get("thread_id")
    except Exception:
        return None


def session_problem(context) -> str | None:
    """Identity must be usable, and it must match whoever opened this thread."""
    problem = identity_problem(context)
    if problem:
        return problem

    thread = thread_id()
    if thread is None:
        return None
    try:
        owner = support_db.bind_thread(thread, context.customer_id)
    except (sqlite3.Error, OSError):
        # Ownership cannot be confirmed, so refuse rather than assume it is fine.
        return DATA_UNAVAILABLE
    return None if owner == context.customer_id else WRONG_OWNER


def refusal(problem: str) -> dict:
    return {"messages": [AIMessage(problem)], "jump_to": "end"}


def refused_call(request, problem: str) -> ToolMessage:
    return ToolMessage(
        content=problem,
        name=request.tool_call["name"],
        tool_call_id=request.tool_call["id"],
        status="error",
    )


def tool_error(error: Exception, request=None) -> str | None:
    """Returning None lets the exception through; some failures must not be softened.

    PermissionError subclasses OSError, so it is tested first. The other order
    would turn an authorisation failure into a friendly "try again later".
    """
    if isinstance(error, PermissionError):
        return None
    if isinstance(error, (sqlite3.Error, OSError)):
        return DATA_UNAVAILABLE
    if isinstance(error, ValueError):
        return BAD_REQUEST
    return None


async def atool_error(error: Exception, request=None) -> str | None:
    return tool_error(error)


class IdentityMiddleware(AgentMiddleware):
    """Refuses the run before any model or tool call when the session is not usable."""

    @hook_config(can_jump_to=["end"])
    def before_agent(self, state, runtime) -> dict | None:
        problem = session_problem(runtime.context)
        return refusal(problem) if problem else None

    @hook_config(can_jump_to=["end"])
    async def abefore_agent(self, state, runtime) -> dict | None:
        problem = await asyncio.to_thread(session_problem, runtime.context)
        return refusal(problem) if problem else None

    def wrap_tool_call(self, request, handler):
        problem = session_problem(request.runtime.context)
        return refused_call(request, problem) if problem else handler(request)

    async def awrap_tool_call(self, request, handler):
        problem = await asyncio.to_thread(session_problem, request.runtime.context)
        return refused_call(request, problem) if problem else await handler(request)

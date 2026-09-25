from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain.agents.middleware import (
    HumanInTheLoopMiddleware,
    ModelFallbackMiddleware,
)
from langgraph.checkpoint.memory import InMemorySaver

from chinook_agent import models
from chinook_agent.context import CustomerContext
from chinook_agent.prompt import SYSTEM_PROMPT
from chinook_agent.tools import TOOLS


load_dotenv()


APPROVAL = HumanInTheLoopMiddleware(
    interrupt_on={
        "request_refund_or_swap": {"allowed_decisions": ["approve", "reject"]}
    },
    description_prefix="Review this refund or replacement before it is recorded",
)


def build_agent(checkpointer=None):
    spares = models.fallbacks()
    middleware = [ModelFallbackMiddleware(*spares)] if spares else []
    middleware.append(APPROVAL)
    return create_agent(
        model=models.primary(),
        tools=TOOLS,
        system_prompt=SYSTEM_PROMPT,
        middleware=middleware,
        context_schema=CustomerContext,
        checkpointer=checkpointer or InMemorySaver(),
    )


def graph():
    """Studio entrypoint. The Agent Server supplies its own checkpointer."""
    return build_agent(checkpointer=None)

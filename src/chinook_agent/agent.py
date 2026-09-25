from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain.agents.middleware import (
    HumanInTheLoopMiddleware,
    ModelCallLimitMiddleware,
    ModelFallbackMiddleware,
    ModelRetryMiddleware,
    ToolCallLimitMiddleware,
    ToolErrorMiddleware,
)
from langgraph.checkpoint.memory import InMemorySaver

from chinook_agent import config, models
from chinook_agent.middleware import (
    IdentityMiddleware,
    atool_error,
    model_failure,
    tool_error,
)
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


def middleware_stack(spares):
    # Identity first: wrap hooks nest outwards, so its refusals stay outside the
    # error handler and can never be rewritten as a friendly retry.
    stack = [
        IdentityMiddleware(),
        ToolErrorMiddleware(tool_error, aon_error=atool_error),
        ModelCallLimitMiddleware(
            run_limit=config.MODEL_CALLS_PER_RUN,
            thread_limit=config.MODEL_CALLS_PER_THREAD,
            exit_behavior="end",
        ),
        ToolCallLimitMiddleware(
            run_limit=config.TOOL_CALLS_PER_RUN,
            thread_limit=config.TOOL_CALLS_PER_THREAD,
            exit_behavior="end",
        ),
    ]
    # Retry outside fallback: one attempt walks the whole chain, and a retry
    # walks it again. The other order leaves the fallback unreachable.
    stack.append(
        ModelRetryMiddleware(
            max_retries=config.MODEL_MAX_RETRIES,
            initial_delay=1.0,
            jitter=True,
            on_failure=model_failure,
        )
    )
    if spares:
        stack.append(ModelFallbackMiddleware(*spares))
    stack.append(APPROVAL)
    return stack


def build_agent(checkpointer=None):
    spares = models.fallbacks()
    middleware = middleware_stack(spares)
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

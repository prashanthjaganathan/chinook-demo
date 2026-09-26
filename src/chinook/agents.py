from dataclasses import dataclass

from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain.agents.middleware import (
    HumanInTheLoopMiddleware, ModelCallLimitMiddleware, ModelFallbackMiddleware,
    ModelRetryMiddleware, ToolCallLimitMiddleware, ToolErrorMiddleware,
)
from langchain.tools import ToolRuntime, tool

from chinook import config, models, prompts
from chinook.context import CustomerContext
from chinook.middleware import AuthMiddleware, SessionGuard, atool_error, model_failure, tool_error
from chinook.tools import (
    get_invoice, get_my_library, price_completion, request_refund_or_swap, resolve_customer,
    search_catalog,
)

load_dotenv()


@dataclass(frozen=True)
class AgentSpec:
    name: str
    description: str
    prompt: str
    tools: tuple
    approvals: tuple = ()


SUBAGENTS = (
    AgentSpec(
        "music_recommendation",
        "Finds albums the customer has partly bought and prices the missing tracks.",
        prompts.MUSIC_RECOMMENDATION_PROMPT,
        (get_my_library, search_catalog, price_completion),
    ),
    AgentSpec(
        "invoice_support",
        "Handles purchases that will not play: diagnoses the format, offers a refund or a swap.",
        prompts.INVOICE_SUPPORT_PROMPT,
        (get_my_library, get_invoice, search_catalog, request_refund_or_swap),
        approvals=("request_refund_or_swap",),
    ),
)


def spec_named(name: str) -> AgentSpec:
    return next(spec for spec in SUBAGENTS if spec.name == name)


def approval(spec: AgentSpec) -> list:
    if not spec.approvals:
        return []
    return [HumanInTheLoopMiddleware(
        interrupt_on={name: {"allowed_decisions": ["approve", "reject"]} for name in spec.approvals},
        description_prefix="Review this before it is recorded",
    )]


def limits(model_calls: int, tool_calls: int, model_thread=None, tool_thread=None) -> list:
    return [
        ModelCallLimitMiddleware(run_limit=model_calls, thread_limit=model_thread, exit_behavior="end"),
        ToolCallLimitMiddleware(run_limit=tool_calls, thread_limit=tool_thread, exit_behavior="end"),
    ]


def resilience(spares) -> list:
    # Retry outside fallback: one attempt walks the whole chain, a retry walks it again.
    stack = [ModelRetryMiddleware(max_retries=config.MODEL_MAX_RETRIES, on_failure=model_failure)]
    return stack + ([ModelFallbackMiddleware(*spares)] if spares else [])


def subagent_middleware(spec: AgentSpec, spares=()) -> list:
    return [
        SessionGuard(),
        ToolErrorMiddleware(tool_error, aon_error=atool_error),
        *limits(config.SUBAGENT_MODEL_CALLS_PER_RUN, config.SUBAGENT_TOOL_CALLS_PER_RUN),
        *resilience(spares),
        *approval(spec),
    ]


def configured(model):
    # An injected model replaces the configured chain entirely, fallbacks included.
    return (models.primary(), models.fallbacks()) if model is None else (model, [])


def build_subagent(spec: AgentSpec, model=None, checkpointer=None):
    model, spares = configured(model)
    # Subagents normally get no checkpointer, so an approval pause surfaces at the supervisor.
    return create_agent(
        model=model,
        tools=list(spec.tools),
        system_prompt=spec.prompt,
        middleware=subagent_middleware(spec, spares),
        context_schema=CustomerContext,
        checkpointer=checkpointer,
        name=spec.name,
    )


def delegate(spec: AgentSpec, subagent):
    @tool(f"ask_{spec.name}", description=spec.description)
    def ask(task: str, runtime: ToolRuntime[CustomerContext]) -> str:
        result = subagent.invoke(
            {"messages": [{"role": "user", "content": task}]},
            context=CustomerContext(customer_id=resolve_customer(runtime)),
        )
        return result["messages"][-1].text

    return ask


def supervisor_middleware(auth=None, spares=()) -> list:
    return [
        auth or AuthMiddleware(),
        *limits(config.SUPERVISOR_MODEL_CALLS_PER_RUN, config.SUPERVISOR_TOOL_CALLS_PER_RUN,
                config.SUPERVISOR_MODEL_CALLS_PER_THREAD, config.SUPERVISOR_TOOL_CALLS_PER_THREAD),
        *resilience(spares),
    ]


def build_supervisor(checkpointer=None, model=None, subagent_model=None, specs=SUBAGENTS, auth=None):
    model, spares = configured(model)
    return create_agent(
        model=model,
        tools=[delegate(spec, build_subagent(spec, model=subagent_model)) for spec in specs],
        system_prompt=prompts.supervisor_prompt(specs),
        middleware=supervisor_middleware(auth, spares),
        context_schema=CustomerContext,
        checkpointer=checkpointer,
        name="supervisor",
    )


def graph():
    """Studio entrypoint. The server supplies its own checkpointer and refuses one of ours."""
    return build_supervisor()

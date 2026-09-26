from dataclasses import dataclass

from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain.agents.middleware import (
    HumanInTheLoopMiddleware, ModelCallLimitMiddleware, ModelFallbackMiddleware,
    ModelRetryMiddleware, ToolCallLimitMiddleware, ToolErrorMiddleware,
)
from langchain.tools import ToolRuntime, tool
from langchain_core.messages import AIMessage, HumanMessage

from chinook import config, models, observability, prompts, tools
from chinook.context import CustomerContext
from chinook.middleware import (
    AuthMiddleware, MustUseATool, PriceGuard, SessionGuard, atool_error, model_failure, tool_error,
)
from chinook.tools import (
    buy_completion, find_purchases, recommend_engine, request_refund, resolve_customer,
    search_catalog,
)

load_dotenv()
observability.enable_masking()


@dataclass(frozen=True)
class AgentSpec:
    name: str
    description: str
    prompt: str
    tools: tuple
    approvals: tuple = ()
    extras: tuple = ()  # middleware classes for this specialist only


SUBAGENTS = (
    AgentSpec(
        "music_recommendation",
        "Recommends music, finds albums to finish, remembers taste, and sells album completions.",
        prompts.MUSIC_RECOMMENDATION_PROMPT,
        (recommend_engine, buy_completion),
        approvals=("buy_completion",),
        extras=(MustUseATool, PriceGuard),
    ),
    AgentSpec(
        "invoice_support",
        "Handles refunds and replacements, including purchases that will not play.",
        prompts.INVOICE_SUPPORT_PROMPT,
        (find_purchases, search_catalog, request_refund),
        approvals=("request_refund",),
        extras=(MustUseATool, PriceGuard),
    ),
)


def spec_named(name: str) -> AgentSpec:
    return next(spec for spec in SUBAGENTS if spec.name == name)


def approval(spec: AgentSpec) -> list:
    if not spec.approvals:
        return []
    return [HumanInTheLoopMiddleware(
        interrupt_on={name: {"allowed_decisions": ["approve", "reject"],
                             "description": tools.APPROVAL_TEXT.get(name, "Review this before it is recorded")}
                      for name in spec.approvals},
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
        *[extra() for extra in spec.extras],
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


def recent_turns(messages) -> str:
    turns = [f"{'Customer' if isinstance(m, HumanMessage) else 'Assistant'}: {m.text}"
             for m in messages
             if isinstance(m, (HumanMessage, AIMessage)) and m.text and not getattr(m, "tool_calls", None)]
    return "\n".join(turns[-config.DELEGATE_TURNS:])


def delegate(spec: AgentSpec, subagent):
    @tool(f"ask_{spec.name}", description=spec.description)
    def ask(task: str, runtime: ToolRuntime[CustomerContext]) -> str:
        # The customer's own words, and what was already asked, survive a paraphrased task.
        turns = recent_turns((runtime.state or {}).get("messages", []))
        content = f"{task}\n\nRecent conversation:\n{turns}" if turns else task
        result = subagent.invoke(
            {"messages": [{"role": "user", "content": content}]},
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
    """Studio entrypoint"""
    return build_supervisor()

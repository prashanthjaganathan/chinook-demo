from dataclasses import dataclass

from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain.agents.middleware import HumanInTheLoopMiddleware
from langchain.tools import ToolRuntime, tool

from chinook import models, prompts
from chinook.context import CustomerContext
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


def subagent_middleware(spec: AgentSpec) -> list:
    return approval(spec)


def build_subagent(spec: AgentSpec, model=None, checkpointer=None):
    # Subagents normally get no checkpointer, so an approval pause surfaces at the supervisor.
    return create_agent(
        model=model or models.primary(),
        tools=list(spec.tools),
        system_prompt=spec.prompt,
        middleware=subagent_middleware(spec),
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


def supervisor_middleware() -> list:
    return []


def build_supervisor(checkpointer=None, model=None, subagent_model=None, specs=SUBAGENTS):
    return create_agent(
        model=model or models.primary(),
        tools=[delegate(spec, build_subagent(spec, model=subagent_model)) for spec in specs],
        system_prompt=prompts.supervisor_prompt(specs),
        middleware=supervisor_middleware(),
        context_schema=CustomerContext,
        checkpointer=checkpointer,
        name="supervisor",
    )


def graph():
    """Studio entrypoint. The server supplies its own checkpointer and refuses one of ours."""
    return build_supervisor()

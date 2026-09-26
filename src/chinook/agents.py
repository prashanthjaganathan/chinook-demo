from dataclasses import dataclass

from dotenv import load_dotenv
from langchain.agents import create_agent

from chinook import models, prompts
from chinook.context import CustomerContext
from chinook.tools import get_invoice, get_my_library, price_completion, search_catalog

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
        (get_my_library, get_invoice, search_catalog),
    ),
)


def spec_named(name: str) -> AgentSpec:
    return next(spec for spec in SUBAGENTS if spec.name == name)


def build_subagent(spec: AgentSpec, model=None):
    return create_agent(
        model=model or models.primary(),
        tools=list(spec.tools),
        system_prompt=spec.prompt,
        context_schema=CustomerContext,
        name=spec.name,
    )

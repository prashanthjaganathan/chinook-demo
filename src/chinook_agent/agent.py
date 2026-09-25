from langchain.agents import create_agent
from langchain.agents.middleware import ModelFallbackMiddleware

from chinook_agent import models
from chinook_agent.context import CustomerContext
from chinook_agent.prompt import SYSTEM_PROMPT
from chinook_agent.tools import TOOLS


def build_agent():
    spares = models.fallbacks()
    return create_agent(
        model=models.primary(),
        tools=TOOLS,
        system_prompt=SYSTEM_PROMPT,
        middleware=[ModelFallbackMiddleware(*spares)] if spares else [],
        context_schema=CustomerContext,
    )

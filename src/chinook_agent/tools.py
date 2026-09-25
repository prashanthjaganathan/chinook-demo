from decimal import Decimal

from langchain.tools import ToolRuntime, tool

from chinook_agent import db
from chinook_agent.context import CustomerContext


def readable(rows: list[dict]) -> list[dict]:
    return [
        {
            key: str(value) if isinstance(value, Decimal) else value
            for key, value in row.items()
        }
        for row in rows
    ]


@tool
def get_my_library(runtime: ToolRuntime[CustomerContext]) -> list[dict]:
    """List the tracks this customer already owns.

    Takes no arguments; the customer comes from the signed-in session.
    Returns each track with its album, artist, genre, format, and price.
    """
    return readable(db.get_library(runtime.context.customer_id))


TOOLS = [get_my_library]

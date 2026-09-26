"""Talk to the agent in the terminal, as a chosen customer.

Approvals are a y/n prompt here rather than hand-typed JSON, because a malformed
resume payload breaks the thread for good.

    uv run python scripts/chat.py 48
"""

import sys
import uuid

from dotenv import load_dotenv
from langgraph.types import Command

load_dotenv()

from chinook_agent import agent  # noqa: E402  (keys must load first)
from chinook_agent.context import CustomerContext  # noqa: E402


def say(result) -> None:
    for message in result["messages"]:
        for call in getattr(message, "tool_calls", None) or []:
            print(f"  · {call['name']}({', '.join(f'{k}={v!r}' for k, v in call['args'].items())})")
    print(f"\n{result['messages'][-1].text}\n")


def main() -> None:
    customer_id = int(sys.argv[1]) if len(sys.argv) > 1 else 48
    graph = agent.build_agent()
    context = CustomerContext(customer_id=customer_id)
    config = {"configurable": {"thread_id": f"chat-{uuid.uuid4().hex[:8]}"}}

    print(f"Signed in as customer {customer_id}. Ctrl-C to leave.\n")
    while True:
        try:
            said = input("you: ").strip()
        except (EOFError, KeyboardInterrupt):
            return
        if not said:
            continue

        result = graph.invoke(
            {"messages": [{"role": "user", "content": said}]},
            config=config,
            context=context,
        )
        while "__interrupt__" in result:
            print(f"\n  REVIEW: {result['__interrupt__'][0].value}")
            decision = "approve" if input("  approve? [y/N] ").strip().lower() == "y" else "reject"
            result = graph.invoke(
                Command(resume={"decisions": [{"type": decision}]}),
                config=config,
                context=context,
            )
        say(result)


if __name__ == "__main__":
    main()

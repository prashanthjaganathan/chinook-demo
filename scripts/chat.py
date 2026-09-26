"""Talk to the supervisor in the terminal. Approvals are y/n, never hand-typed JSON.

    uv run python scripts/chat.py 48        # signed in as customer 48
    uv run python scripts/chat.py           # anonymous
"""

import sys
import uuid

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from chinook.agents import build_supervisor
from chinook.context import CustomerContext


def main() -> None:
    customer_id = int(sys.argv[1]) if len(sys.argv) > 1 else None
    graph = build_supervisor(checkpointer=InMemorySaver())
    context = CustomerContext(customer_id=customer_id)
    config = {"configurable": {"thread_id": f"chat-{uuid.uuid4().hex[:8]}"}}
    print(f"Customer: {customer_id or 'anonymous'}. Ctrl-C to leave.\n")

    while True:
        try:
            said = input("you: ").strip()
        except (EOFError, KeyboardInterrupt):
            return
        if not said:
            continue
        result = graph.invoke({"messages": [{"role": "user", "content": said}]},
                              config=config, context=context)
        while "__interrupt__" in result:
            request = result["__interrupt__"][0].value["action_requests"][0]
            print(f"\n  REVIEW {request['name']}: {request['args']}")
            decision = "approve" if input("  approve? [y/N] ").strip().lower() == "y" else "reject"
            result = graph.invoke(Command(resume={"decisions": [{"type": decision}]}),
                                  config=config, context=context)
        print(f"\n{result['messages'][-1].text}\n")


if __name__ == "__main__":
    main()

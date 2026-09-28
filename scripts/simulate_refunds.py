"""Send realistic refund requests through the full agent, approve each confirmation, and report the outcome.

    uv run python scripts/simulate_refunds.py --count 20
Traces are tagged "simulated", with refund outcomes attached as feedback for LangSmith dashboards.
Refunds go to a scratch store, never data/support.sqlite.
"""
import argparse
import os
import random
import tempfile
import uuid
from collections import Counter
from decimal import Decimal
from pathlib import Path

os.environ["SUPPORT_DB"] = str(Path(tempfile.mkdtemp(prefix="chinook_sim_")) / "support.sqlite")

from langgraph.checkpoint.memory import InMemorySaver  # noqa: E402
from langgraph.types import Command  # noqa: E402

from chinook.agent import outcomes  # noqa: E402
from chinook.agent.team import build_supervisor  # noqa: E402
from chinook.foundation import config  # noqa: E402
from chinook.foundation.context import CustomerContext  # noqa: E402
from chinook.helpers import catalog, store  # noqa: E402

# How often each kind of request arrives, and what the customer says.
SCENARIOS = {
    "protected_on_android": (4, True, "{track} won't play on my Android phone, please refund it"),
    "swap_for_android": (2, True, "{track} won't play on my Android, can you swap it for something that plays?"),
    "mp3_wont_play": (2, False, "{track} won't play on my laptop, please refund it"),
    "bought_by_mistake": (2, False, "I bought {track} by mistake, please refund it"),
    "didnt_like_it": (1, False, "I didn't like {track}, can I get a refund?"),
}


def requests(count: int, seed: int) -> list[tuple[str, int, str]]:
    rng = random.Random(seed)
    kinds = rng.choices(list(SCENARIOS), weights=[w for w, _, _ in SCENARIOS.values()], k=count)
    picked, used = [], set()
    for kind in kinds:
        _, protected, text = SCENARIOS[kind]
        customer = rng.randint(1, 59)
        lines = [l for l in catalog.customer_purchases(customer)
                 if config.plays_anywhere(l["media_type"]) != protected and (customer, l["track"]) not in used]
        if lines:
            track = rng.choice(lines)["track"]
            used.add((customer, track))
            picked.append((kind, customer, text.format(track=track)))
    return picked


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=20)
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()

    graph = build_supervisor(checkpointer=InMemorySaver())
    asked = 0
    for kind, customer, message in requests(args.count, args.seed):
        run = {"configurable": {"thread_id": str(uuid.uuid4())}, "tags": ["simulated"],
               "metadata": {"simulated": True, "scenario": kind}}
        context = CustomerContext(customer_id=customer)
        result = graph.invoke({"messages": [{"role": "user", "content": message}]}, config=run, context=context)
        if "__interrupt__" not in result:
            asked += 1
        while "__interrupt__" in result:
            result = graph.invoke(Command(resume={"decisions": [{"type": "approve"}]}), config=run, context=context)
        print(f"{kind:22} customer {customer:>2}  {result['messages'][-1].text[:80]!r}")

    rows = store.execute("SELECT status, action, amount FROM refund_requests")
    bands = Counter(row["status"] for row in rows)
    without_staff = [row for row in rows if row["status"] != "needs_review"]
    retained = sum((Decimal(row["amount"]) for row in rows if row["action"] == "swap"), Decimal(0))
    print(f"\nRequests recorded: {len(rows)}  (agent asked a question instead: {asked})")
    print("Band mix:", dict(bands))
    if rows:
        print(f"Handled without staff: {len(without_staff)}/{len(rows)} = {len(without_staff) / len(rows):.0%}")
    print(f"Staff cost saved: ${outcomes.STAFF_COST_PER_REFUND * len(without_staff):.2f}"
          f"  (assumed {config.ASSUMED_MINUTES_PER_MANUAL_REFUND} min at ${config.ASSUMED_SUPPORT_COST_PER_HOUR}/h)")
    print(f"Revenue retained by swaps: ${retained:.2f}")


if __name__ == "__main__":
    main()

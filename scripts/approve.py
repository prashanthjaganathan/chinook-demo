"""Approve or reject a paused refund without hand-typing JSON.

A malformed resume payload is written into the checkpoint and breaks the thread
for good, so the only safe approval is one built from a fixed choice.
"""

import sys

import httpx

URL = "http://127.0.0.1:2024"
DECISIONS = ("approve", "reject")


def payload(decision: str) -> dict:
    if decision not in DECISIONS:
        raise ValueError(f"decision must be one of {', '.join(DECISIONS)}")
    return {"decisions": [{"type": decision}]}


def send(thread_id: str, assistant_id: str, decision: str, customer_id: int) -> dict:
    with httpx.Client(base_url=URL, timeout=120) as client:
        response = client.post(
            f"/threads/{thread_id}/runs/wait",
            json={
                "assistant_id": assistant_id,
                "command": {"resume": payload(decision)},
                "context": {"customer_id": customer_id},
            },
        )
        response.raise_for_status()
        return response.json()


def main() -> None:
    if len(sys.argv) != 5:
        print("usage: approve.py THREAD_ID ASSISTANT_ID approve|reject CUSTOMER_ID")
        raise SystemExit(2)

    thread_id, assistant_id, decision, customer_id = sys.argv[1:]
    result = send(thread_id, assistant_id, decision, int(customer_id))
    print(result["messages"][-1].get("content", result["messages"][-1]))


if __name__ == "__main__":
    main()

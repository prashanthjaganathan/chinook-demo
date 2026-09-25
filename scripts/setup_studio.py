"""Creates the named Studio assistants that carry a customer identity.

Studio's input panel does not expose runtime context, so each demo identity gets
its own assistant. Re-running updates them instead of making duplicates.
"""

import httpx

URL = "http://127.0.0.1:2024"
GRAPH = "support"

ASSISTANTS = {
    "support - customer 48": 48,
    "support - customer 4": 4,
    "support - Aaron Mitchell (32)": 32,
    "support - anonymous": None,
}


def upsert(client: httpx.Client, name: str, customer_id: int | None) -> str:
    found = client.post(
        "/assistants/search", json={"graph_id": GRAPH, "limit": 100}
    ).json()
    for assistant in found:
        if assistant.get("name") == name:
            client.patch(
                f"/assistants/{assistant['assistant_id']}",
                json={"context": {"customer_id": customer_id}},
            ).raise_for_status()
            return assistant["assistant_id"]

    created = client.post(
        "/assistants",
        json={
            "graph_id": GRAPH,
            "name": name,
            "context": {"customer_id": customer_id},
        },
    )
    created.raise_for_status()
    return created.json()["assistant_id"]


def main() -> None:
    with httpx.Client(base_url=URL, timeout=30) as client:
        for name, customer_id in ASSISTANTS.items():
            assistant_id = upsert(client, name, customer_id)
            print(f"{name:32} customer={customer_id}  {assistant_id}")


if __name__ == "__main__":
    main()

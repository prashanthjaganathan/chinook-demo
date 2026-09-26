"""Creates Studio assistants that carry a customer identity. Re-running updates them."""

import httpx

URL = "http://127.0.0.1:2024"
ASSISTANTS = {"customer 48": 48, "customer 54": 54, "anonymous": None}


def main() -> None:
    with httpx.Client(base_url=URL, timeout=30) as client:
        existing = {a["name"]: a["assistant_id"]
                    for a in client.post("/assistants/search", json={"graph_id": "support", "limit": 100}).json()}
        for name, customer_id in ASSISTANTS.items():
            body = {"context": {"customer_id": customer_id}}
            if name in existing:
                client.patch(f"/assistants/{existing[name]}", json=body).raise_for_status()
            else:
                client.post("/assistants", json={"graph_id": "support", "name": name, **body}).raise_for_status()
            print(f"{name}: customer_id={customer_id}")


if __name__ == "__main__":
    main()

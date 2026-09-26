"""Staff queue: approve or reject refunds the policy sent for review.

    uv run python scripts/review.py
"""

from dotenv import load_dotenv

from chinook import catalog, store


def main() -> None:
    load_dotenv()
    tracks = {row["id"]: row["label"] for row in catalog.names("track")}
    waiting = store.waiting_for_review()
    if not waiting:
        print("Nothing waiting for review.")
    for row in waiting:
        print(f"\n{tracks.get(row['track_id'])}  ${row['amount']}  customer {row['customer_id']}")
        print(f"  {row['action']}: {row['reason']}  score {row['score']}  policy {row['policy']}")
        answer = input("  approve, reject, or skip? [a/r/S] ").strip().lower()
        if answer in ("a", "r"):
            store.review(row["request_key"], approved=answer == "a")


if __name__ == "__main__":
    main()

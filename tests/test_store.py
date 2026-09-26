import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest

from chinook import catalog, store


def a_request(**overrides):
    return {"customer_id": 54, "invoice_line_id": 1111, "track_id": 1504, "action": "refund",
            "replacement_track_id": None, "amount": "0.99", "reason": "will not play", **overrides}


def test_a_replayed_request_is_recorded_once():
    store.record("k1", **a_request())
    store.record("k1", **a_request())

    assert len(store.open_requests(54)) == 1


def test_a_replay_with_different_details_is_rejected():
    store.record("k1", **a_request())

    with pytest.raises(ValueError):
        store.record("k1", **a_request(track_id=1))


def test_a_second_thread_cannot_refund_the_same_line():
    store.record("thread-a", **a_request())

    with pytest.raises(sqlite3.IntegrityError):
        store.record("thread-b", **a_request())


def test_twenty_concurrent_writes_succeed():
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda n: store.record(f"k{n}", **a_request(invoice_line_id=n)), range(1, 21)))

    assert len(store.open_requests(54)) == 20


def test_the_store_refuses_to_be_the_chinook_database(monkeypatch):
    monkeypatch.setenv("SUPPORT_DB", str(catalog.DB_PATH))

    with pytest.raises(ValueError):
        store.connect()


def test_the_first_claim_on_a_thread_wins():
    assert store.bind_thread("t1", 54) == 54
    assert store.bind_thread("t1", 4) == 54

    with ThreadPoolExecutor(max_workers=8) as pool:
        assert len(set(pool.map(lambda c: store.bind_thread("race", c), range(1, 9)))) == 1


def test_request_keys_are_scoped_to_thread_and_call():
    assert store.request_key("t1", "c1") == store.request_key("t1", "c1")
    assert len({store.request_key(t, c) for t, c in [("t1", "c1"), ("t2", "c1"), ("t1", "c2")]}) == 3


def test_preferences_are_empty_then_upserted():
    assert store.get_preferences(48) == {}
    store.save_preferences(48, {"genres": ["Rock"]})
    store.save_preferences(48, {"genres": ["Jazz"], "device": "apple"})

    assert store.get_preferences(48) == {"genres": ["Jazz"], "device": "apple"}
    assert store.get_preferences(54) == {}


def test_a_replayed_order_is_recorded_once():
    order = {"customer_id": 48, "album_id": 205, "offer_id": "205-abc", "amount": "4.75"}
    first = store.record_order("k1", **order)
    again = store.record_order("k1", **{**order, "amount": "0.01"})

    assert first == again and again["amount"] == "4.75"
    assert len(store.execute("SELECT * FROM orders")) == 1

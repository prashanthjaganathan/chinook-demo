import pytest

import find_demo_customer
from chinook_agent import config, db


@pytest.fixture(scope="module")
def ranked():
    return find_demo_customer.rank()


def test_named_demo_candidates_are_all_usable(ranked):
    assert {48, 54, 7} <= {row["customer_id"] for row in ranked}


def test_customer_48_ranks_in_the_top_three(ranked):
    assert 48 in [row["customer_id"] for row in ranked[:3]]


def test_candidates_are_ordered_by_completion_ratio(ranked):
    ratios = [row["ratio"] for row in ranked]

    assert ratios == sorted(ratios, reverse=True)


def test_every_candidate_can_carry_both_workflows(ranked):
    assert ranked
    for row in ranked:
        assert find_demo_customer.MIN_OWNED <= row["owned_tracks"] < row["total_tracks"]
        assert row["total_tracks"] >= find_demo_customer.MIN_ALBUM_TRACKS
        assert row["swap_options"] >= 1
        assert row["protected_owned"] >= 1


def test_the_suggested_refund_line_is_on_that_customers_invoice(ranked):
    for row in ranked[:3]:
        invoice = db.get_invoice(row["customer_id"], row["invoice_id"])
        lines = {line["invoice_line_id"]: line for line in invoice["lines"]}

        assert row["invoice_line_id"] in lines
        assert lines[row["invoice_line_id"]]["track_id"] == row["swap_track_id"]


def test_the_suggested_swap_track_is_protected_and_owned(ranked):
    for row in ranked[:3]:
        owned = {track["track_id"]: track for track in db.get_library(row["customer_id"])}

        assert row["swap_track_id"] in owned
        assert not config.plays_anywhere(owned[row["swap_track_id"]]["media_type"])


def test_a_suggested_swap_passes_the_real_swap_check(ranked):
    for row in ranked[:3]:
        customer_id = row["customer_id"]
        track = next(
            item
            for item in db.get_library(customer_id)
            if item["track_id"] == row["swap_track_id"]
        )
        replacement = find_demo_customer.swap_options(customer_id, track)[0]

        assert db.check_swap(customer_id, row["swap_track_id"], replacement["track_id"]) is None

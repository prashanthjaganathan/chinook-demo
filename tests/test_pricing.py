from decimal import Decimal

import pytest

from chinook.helpers import catalog, pricing


def test_six_tracks_at_99_cents():
    assert pricing.completion_price([Decimal("0.99")] * 6) == {
        "list_price": Decimal("5.94"), "discount": Decimal("1.19"), "final_price": Decimal("4.75")}


def test_final_plus_discount_equals_list_for_every_partial_album():
    results = [
        pricing.completion_price([t["unit_price"] for t in catalog.missing_tracks(c, a["album_id"])])
        for c in range(1, 60) for a in catalog.partial_albums(c)
    ]

    assert len(results) == 1252
    assert all(r["final_price"] + r["discount"] == r["list_price"] for r in results)
    assert all(0 <= r["final_price"] <= r["list_price"] for r in results)


def test_half_cent_rounds_up_and_invariant_holds():
    result = pricing.completion_price([Decimal("3.125")])

    assert result["discount"] == Decimal("0.63")
    assert result["final_price"] + result["discount"] == result["list_price"]


def test_tv_season_is_priced_at_199():
    prices = [t["unit_price"] for t in catalog.missing_tracks(46, 231)]

    assert prices == [Decimal("1.99")] * 17
    assert pricing.completion_price(prices)["final_price"] == Decimal("27.06")


def test_floats_and_negatives_are_rejected():
    for value in (0.99, "0.99", None, Decimal("-1"), True):
        with pytest.raises(ValueError):
            pricing.completion_price([value])


def test_a_bundle_price_splits_into_shares_that_add_up_exactly():
    assert pricing.split_evenly(Decimal("1.00"), 3) == [Decimal("0.33"), Decimal("0.33"), Decimal("0.34")]
    shares = pricing.split_evenly(Decimal("4.16"), 6)
    assert sum(shares) == Decimal("4.16") and max(shares) - min(shares) <= Decimal("0.05")

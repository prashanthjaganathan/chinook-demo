from decimal import Decimal

import pytest

from chinook_agent import config, db, pricing

LOST_SEASON_2 = 231


@pytest.fixture(scope="module")
def every_partial_album_price():
    results = []
    for customer_id in range(1, 60):
        for album in db.partial_albums(customer_id):
            prices = [
                row["unit_price"]
                for row in db.missing_tracks(customer_id, album["album_id"])
            ]
            results.append(pricing.completion_price(prices))
    return results


def test_six_tracks_at_99_cents():
    assert pricing.completion_price([Decimal("0.99")] * 6) == {
        "list_price": Decimal("5.94"),
        "discount": Decimal("1.19"),
        "final_price": Decimal("4.75"),
    }


def test_no_tracks_costs_nothing():
    result = pricing.completion_price([])

    assert result["list_price"] == result["discount"] == result["final_price"] == 0


def test_result_is_decimal_not_float():
    result = pricing.completion_price([Decimal("0.99")] * 3)

    assert all(isinstance(value, Decimal) for value in result.values())
    assert result["list_price"] == Decimal("2.97")


def test_rounding_is_half_up_not_bankers():
    assert pricing.completion_price([Decimal("3.125")])["discount"] == Decimal("0.63")


def test_invariant_holds_when_the_discount_lands_on_half_a_cent():
    result = pricing.completion_price([Decimal("3.125")])

    assert result["final_price"] + result["discount"] == result["list_price"]


def test_float_prices_are_rejected():
    for value in (0.99, "0.99", None, Decimal("-0.99"), True, [Decimal("0.99")]):
        with pytest.raises(ValueError):
            pricing.completion_price([value])


def test_discount_outside_zero_to_one_is_rejected():
    for value in (Decimal("-0.1"), Decimal("1"), Decimal("1.5"), 0.2, None, True):
        with pytest.raises(ValueError):
            config.valid_discount(value)


def test_configured_discount_is_twenty_percent():
    assert config.COMPLETION_DISCOUNT == Decimal("0.20")


def test_199_album_completion_is_priced_at_199():
    prices = [row["unit_price"] for row in db.missing_tracks(46, LOST_SEASON_2)]
    result = pricing.completion_price(prices)

    assert prices == [Decimal("1.99")] * 17
    assert result["list_price"] == Decimal("33.83")
    assert result["discount"] == Decimal("6.77")
    assert result["final_price"] == Decimal("27.06")


def test_final_plus_discount_equals_list_for_every_partial_album(every_partial_album_price):
    assert len(every_partial_album_price) == 1252
    assert all(
        result["final_price"] + result["discount"] == result["list_price"]
        for result in every_partial_album_price
    )


def test_final_price_is_never_negative_or_above_list(every_partial_album_price):
    assert all(
        Decimal("0") <= result["final_price"] <= result["list_price"]
        for result in every_partial_album_price
    )

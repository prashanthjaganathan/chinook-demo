from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal

from chinook.foundation.config import COMPLETION_DISCOUNT

CENT = Decimal("0.01")


def completion_price(prices: list[Decimal]) -> dict:
    list_price = Decimal("0")
    for price in prices:
        if not isinstance(price, Decimal) or price < 0:
            raise ValueError("prices must be non-negative Decimals")
        list_price += price
    # Round the discount, not the final price, so final + discount == list exactly.
    discount = (list_price * COMPLETION_DISCOUNT).quantize(CENT, rounding=ROUND_HALF_UP)
    return {"list_price": list_price, "discount": discount, "final_price": list_price - discount}


def split_evenly(total: Decimal, count: int) -> list[Decimal]:
    """Each track's share of a bundle price; the last takes the leftover cents, so they add up exactly."""
    share = (total / count).quantize(CENT, rounding=ROUND_DOWN)
    return [share] * (count - 1) + [total - share * (count - 1)]

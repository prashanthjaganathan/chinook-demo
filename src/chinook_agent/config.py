from decimal import Decimal


def valid_discount(value: Decimal) -> Decimal:
    if not isinstance(value, Decimal) or not Decimal("0") <= value < Decimal("1"):
        raise ValueError("discount must be a Decimal from 0 up to but not including 1")
    return value


# Chinook has no album price, so completion needs an explicit discount to be worth taking.
COMPLETION_DISCOUNT = valid_discount(Decimal("0.20"))

import find_demo_customer


def test_star_customer_ranks_near_the_top():
    ranked = find_demo_customer.rank()

    assert 48 in [row["customer_id"] for row in ranked[:3]]
    ratios = [row["ratio"] for row in ranked]
    assert ratios == sorted(ratios, reverse=True)

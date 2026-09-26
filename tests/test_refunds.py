from chinook import catalog, config, refunds


def labels(result):
    return [p["label"] for p in result["purchases"]]


def test_customer_purchases_are_newest_first_with_prices():
    lines = catalog.customer_purchases(54)

    assert len(lines) == 38
    assert lines == sorted(lines, key=lambda l: l["invoice_date"], reverse=True)


def test_a_track_name_finds_the_purchase():
    result = refunds.find(54, track="midnight")

    assert result["status"] == "found"
    assert labels(result)[0].startswith("Midnight by ")
    assert result["reasons"] == config.REFUND_REASON_LABELS


def test_a_misspelled_artist_lists_their_lines_by_that_artist():
    result = refunds.find(42, artist="metalica")

    assert result["status"] == "choose" and len(result["purchases"]) == config.MAX_CANDIDATES
    assert all(" by Metallica, " in label for label in labels(result))


def test_no_clues_shows_the_latest_order():
    lines = catalog.customer_purchases(54)
    latest = [l for l in lines if l["invoice_id"] == lines[0]["invoice_id"]]

    expected = [refunds.label(l) for l in latest][: config.MAX_CANDIDATES]

    assert labels(refunds.find(54)) == labels(refunds.find(54, latest=True)) == expected


def test_android_ranks_protected_lines_first_but_still_finds_an_mp3_by_name():
    locked = {refunds.label(l) for l in catalog.customer_purchases(54)
              if not config.plays_anywhere(l["media_type"])}
    mp3 = refunds.find(54, track="someday never comes", wont_play_on="other")

    assert set(labels(refunds.find(54, wont_play_on="other"))) <= locked
    assert labels(mp3)[0].startswith("Someday Never Comes by ")


def test_another_customers_track_is_never_a_candidate():
    assert refunds.find(1, track="midnight")["status"] == "not_found"

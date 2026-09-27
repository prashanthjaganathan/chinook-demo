from chinook.domain import refunds
from chinook.foundation import config
from chinook.helpers import catalog, store


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


def test_a_ref_resolves_only_for_its_own_customer_and_unedited():
    ref = refunds.find(54, track="midnight")["purchases"][0]["purchase_ref"]
    line_id = ref.split("-")[0]

    assert refunds.purchase_for_ref(54, ref)["track"] == "Midnight"
    assert refunds.purchase_for_ref(1, ref) is None
    assert refunds.purchase_for_ref(54, f"{line_id}-0000000000") is None
    assert refunds.purchase_for_ref(54, line_id) is None
    assert refunds.purchase_for_ref(54, "junk") is None


def line(customer_id, track):
    return next(l for l in catalog.customer_purchases(customer_id) if l["track"] == track)


def outcome(reason, track="Midnight", device="other", customer_id=54):
    decision = refunds.decide(customer_id, line(customer_id, track), reason, device)
    return decision["score"], decision["status"]


def approve_refunds(count):
    for n in range(count):
        store.record(f"k{n}", customer_id=54, invoice_line_id=n + 1, track_id=1, action="refund",
                     replacement_track_id=None, amount="0.99", reason="wont_play",
                     status="approved", score=100, policy="v1")


def test_protected_file_on_android_first_refund_is_auto_approved():
    assert outcome("wont_play") == (100, "auto_approved")


def test_an_mp3_that_wont_play_goes_to_staff():
    assert outcome("wont_play", track="Someday Never Comes") == (65, "needs_review")


def test_a_protected_file_on_apple_is_not_explained_by_the_format():
    assert outcome("wont_play", device="apple") == (65, "needs_review")


def test_buying_the_same_track_twice_is_auto_approved(monkeypatch):
    twice = catalog.customer_purchases(54) + [line(54, "Midnight")]
    monkeypatch.setattr(catalog, "customer_purchases", lambda customer_id: twice)

    assert outcome("bought_by_mistake") == (100, "auto_approved")


def test_bought_by_mistake_without_a_duplicate_goes_to_staff():
    assert outcome("bought_by_mistake") == (65, "needs_review")


def test_didnt_like_it_and_no_reason_are_auto_rejected():
    assert outcome("didnt_like_it") == (35, "auto_rejected")
    assert outcome("not_given") == (35, "auto_rejected")


def test_other_always_goes_to_staff():
    assert outcome("other")[1] == "needs_review"


def test_one_recent_refund_costs_points_and_three_escalate():
    approve_refunds(1)
    assert outcome("wont_play") == (80, "auto_approved")

    approve_refunds(3)
    assert outcome("wont_play") == (80, "needs_review")


def test_the_decision_records_its_checks_and_policy_version():
    decision = refunds.decide(54, line(54, "Midnight"), "didnt_like_it", "other")

    assert decision["policy"] == config.REFUND_POLICY_VERSION
    assert set(decision["items"]) == set(config.REFUND_CHECKLIST)
    assert decision["items"]["reason_is_refundable"] is False

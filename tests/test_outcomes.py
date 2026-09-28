from helpers import ref, runtime_for

from chinook.domain import engine

from chinook.agent import outcomes
from chinook.agent.tools import buy_completion, request_refund


def test_staff_cost_comes_from_the_stated_assumptions():
    assert outcomes.STAFF_COST_PER_REFUND == 3


def test_scores_count_staff_time_saved_not_refunds_refused():
    assert outcomes.refund_scores("auto_approved", "refund", "0.99") == {
        "handled_without_staff": 1, "staff_cost_saved": 3.0, "revenue_retained": 0.0}
    assert outcomes.refund_scores("needs_review", "refund", "0.99")["staff_cost_saved"] == 0.0
    assert outcomes.refund_scores("auto_approved", "swap", "0.99")["revenue_retained"] == 0.99


def test_nothing_is_sent_without_a_trace(monkeypatch):
    monkeypatch.setattr(outcomes, "client", lambda: (_ for _ in ()).throw(AssertionError("sent")))

    outcomes.record_refund("auto_approved", "refund", "0.99")


def test_a_recorded_refund_reports_its_outcome_to_the_trace(monkeypatch):
    sent = []

    class Run:
        trace_id = "trace-1"

    class Fake:
        def create_feedback(self, run_id, key, **fields):
            sent.append((run_id, key, fields))

    monkeypatch.setattr(outcomes, "get_current_run_tree", lambda: Run())
    monkeypatch.setattr(outcomes, "client", lambda: Fake())
    request_refund.invoke({"runtime": runtime_for(54), "purchase_ref": ref(), "reason": "wont_play",
                           "device": "other"})

    assert ("trace-1", "refund_band", {"value": "auto_approved"}) in sent
    assert {key for _, key, _ in sent} == {"refund_band", "handled_without_staff", "staff_cost_saved",
                                          "revenue_retained"}


def test_a_dashboard_failure_never_breaks_the_refund(monkeypatch):
    class Run:
        trace_id = "trace-1"

    monkeypatch.setattr(outcomes, "get_current_run_tree", lambda: Run())
    monkeypatch.setattr(outcomes, "client", lambda: (_ for _ in ()).throw(RuntimeError("down")))
    result = request_refund.invoke({"runtime": runtime_for(54), "purchase_ref": ref(), "reason": "wont_play",
                                    "device": "other"})

    assert result["status"] == "auto_approved"


def test_an_album_completion_reports_its_revenue_to_the_trace(monkeypatch):
    sent = []

    class Run:
        trace_id = "trace-1"

    class Fake:
        def create_feedback(self, run_id, key, **fields):
            sent.append((run_id, key, fields))

    offer = next(o for o in engine.recommend(48)["offers"] if o["album"] == "In Step")
    monkeypatch.setattr(outcomes, "get_current_run_tree", lambda: Run())
    monkeypatch.setattr(outcomes, "client", lambda: Fake())
    buy_completion.invoke({"runtime": runtime_for(48), "offer_id": offer["offer_id"]})

    assert ("trace-1", "purchase", {"value": "album_completion"}) in sent
    assert ("trace-1", "completion_revenue", {"score": float(offer["final_price"])}) in sent
    assert ("trace-1", "completion_tracks_sold", {"score": len(offer["missing_tracks"])}) in sent

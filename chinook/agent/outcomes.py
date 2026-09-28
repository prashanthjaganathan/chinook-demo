"""Attaches business outcomes to the conversation's trace, so LangSmith dashboards can count them."""
import logging
from decimal import Decimal
from functools import cache

from langsmith import Client
from langsmith.run_helpers import get_current_run_tree

from chinook.foundation import config

log = logging.getLogger(__name__)

# Stated assumption, not measured: minutes a person spends on one refund, times their hourly cost.
STAFF_COST_PER_REFUND = (Decimal(config.ASSUMED_MINUTES_PER_MANUAL_REFUND) / 60
                         * Decimal(config.ASSUMED_SUPPORT_COST_PER_HOUR))


@cache
def client() -> Client:
    return Client()


def refund_scores(status: str, action: str, amount: str) -> dict:
    without_staff = status != "needs_review"
    return {
        "handled_without_staff": int(without_staff),
        "staff_cost_saved": float(STAFF_COST_PER_REFUND) if without_staff else 0.0,
        "revenue_retained": float(amount) if action == "swap" else 0.0,
    }


def purchase_scores(offer: dict) -> dict:
    return {
        "completion_revenue": float(offer["final_price"]),
        "completion_tracks_sold": len(offer["missing_tracks"]),
        "completion_discount_given": float(offer["discount"]),
    }


def attach(label: tuple[str, str], scores: dict) -> None:
    run = get_current_run_tree()
    if run is None:
        return
    try:
        client().create_feedback(run.trace_id, key=label[0], value=label[1])
        for key, score in scores.items():
            client().create_feedback(run.trace_id, key=key, score=score)
    except Exception as error:
        # A refund or purchase must never fail because the dashboard couldn't be updated.
        log.warning("could not record %s outcome: %s", label[0], error)


def record_refund(status: str, action: str, amount: str) -> None:
    attach(("refund_band", status), refund_scores(status, action, amount))


def record_purchase(offer: dict) -> None:
    attach(("purchase", "album_completion"), purchase_scores(offer))

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


def record_refund(status: str, action: str, amount: str) -> None:
    run = get_current_run_tree()
    if run is None:
        return
    try:
        client().create_feedback(run.trace_id, key="refund_band", value=status)
        for key, score in refund_scores(status, action, amount).items():
            client().create_feedback(run.trace_id, key=key, score=score)
    except Exception as error:
        # A refund must never fail because the dashboard couldn't be updated.
        log.warning("could not record refund outcome: %s", error)

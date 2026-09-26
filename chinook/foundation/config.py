from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Any


def valid_discount(value: Decimal) -> Decimal:
    if not isinstance(value, Decimal) or not Decimal("0") <= value < Decimal("1"):
        raise ValueError("discount must be a Decimal from 0 up to but not including 1")
    return value


# Chinook has no album price, so completion needs an explicit discount.
COMPLETION_DISCOUNT = valid_discount(Decimal("0.20"))

# Apple FairPlay DRM: these formats only play on Apple devices.
PROTECTED_FORMATS = frozenset({"Protected AAC audio file", "Protected MPEG-4 video file"})
VIDEO_FORMATS = frozenset({"Protected MPEG-4 video file"})
MEDIA_TYPES = (
    "MPEG audio file",
    "AAC audio file",
    "Purchased AAC audio file",
    "Protected AAC audio file",
    "Protected MPEG-4 video file",
)


def plays_anywhere(media_type: str) -> bool:
    return media_type not in PROTECTED_FORMATS


def media_kind(media_type: str) -> str:
    return "video" if media_type in VIDEO_FORMATS else "audio"


RECOMMEND_LIMIT = 5
MAX_PREFERENCE_ITEMS = 5
ASK_DEVICE = "Do you listen on an Apple device or something else?"
ASK_GENRES = "What kinds of music do you like?"
OFFER_CHANGED = "That offer has changed. Ask for the album again to get the current price."

RESOLVE_CUTOFF = 0.8
RESOLVE_MARGIN = 0.05
# Nicknames that string matching can't guess, keyed by normalized form.
ALIASES = {"zep": "Led Zeppelin", "gnr": "Guns N' Roses", "rhcp": "Red Hot Chili Peppers"}

MAX_SEARCH_TEXT = 100
MAX_SEARCH_RESULTS = 50
MAX_REASON = 500

NO_IDENTITY = "I cannot see who is signed in, so I cannot open this account."


@dataclass(frozen=True)
class ModelSpec:
    name: str
    api_key_env: str | None = None
    options: Mapping[str, Any] | None = None


# Tried in order. Add a provider by appending; reuse one with a second key via api_key_env.
MODEL_CHAIN = (
    # gpt-5.6-luna rejects function tools on /v1/chat/completions; the Responses API accepts them.
    ModelSpec("openai:gpt-5.6-luna", "OPENAI_API_KEY", {"use_responses_api": True}),
    ModelSpec("anthropic:claude-sonnet-4-6", "ANTHROPIC_API_KEY"),
)
# Legitimate calls reach ~9s; a hung call should fail over to the next model quickly.
MODEL_TIMEOUT_SECONDS = 20
MODEL_MAX_RETRIES = 1
NOT_YOUR_PURCHASE = "That track is not on this account."
REQUEST_NOT_DONE = "The request was not completed, so nothing was changed."
SWAP_APPROVED = "Your replacement is approved."
ALREADY_REQUESTED = "That purchase already has a refund or replacement in progress."

# Refund policy, compiled from the store's policy doc and reviewed. Bump the version on any change.
REFUND_POLICY_VERSION = "v1"
REFUND_REASON_LABELS = {
    "wont_play": "it won't play on my device",
    "bought_by_mistake": "I bought it by mistake",
    "didnt_like_it": "I didn't like it",
    "other": "something else",
    "not_given": "no reason given",
}
REFUNDABLE_REASONS = ("wont_play", "bought_by_mistake")
# Each item is a yes/no computed in code; the score is the sum of the weights that pass.
REFUND_CHECKLIST = {
    "reason_is_refundable": 30,
    "data_supports_reason": 35,
    "first_refund_recently": 20,
    "within_auto_limit": 15,
}
REFUND_BANDS = (40, 70)  # under 40: auto reject; 40 to 69: staff review; 70 and up: auto approve
AUTO_REFUND_LIMIT = Decimal("1.99")
RECENT_REFUND_DAYS = 90
MAX_RECENT_REFUNDS = 3  # at or above this, always staff review
MAX_CANDIDATES = 5
REFUND_MESSAGES = {
    "auto_approved": "Your refund is approved.",
    "needs_review": "I've sent this to our team to review. You'll hear back soon.",
    "auto_rejected": "This doesn't qualify for a refund under our policy. "
                     "I can offer a replacement, or ask a person to take another look.",
}

AUTH_MAX_ATTEMPTS = 3
OTP_LENGTH_RANGE = (4, 8)
ASK_PHONE = "Before I can look at your account, what's the phone number on it?"
NO_PHONE = "I couldn't find a phone number in that. What's the number on your account?"
# Same reply whether or not the number matches, so phone numbers cannot be probed.
CODE_SENT = "If that number is on an account, I've sent a 6-digit code. What is it?"
BAD_CODE = "That code didn't work. Check the number and try again."
AUTH_LOCKED = "I couldn't verify your account. Please start a new conversation."
AUTHENTICATED = "I was able to authenticate you."
WRONG_OWNER = "This conversation belongs to a different account. Please start a new one."
DATA_UNAVAILABLE = "I could not reach the store's records just now, so nothing was checked or changed."
BAD_REQUEST = "That request was not valid, so nothing was changed."
MODEL_UNAVAILABLE = "I could not reach the assistant service just now, so nothing was checked or changed."

# Cost ceiling. Subagents have no checkpointer, so only per-run limits apply to them.
SUPERVISOR_MODEL_CALLS_PER_RUN = 4
SUPERVISOR_TOOL_CALLS_PER_RUN = 3
SUPERVISOR_MODEL_CALLS_PER_THREAD = 40
SUPERVISOR_TOOL_CALLS_PER_THREAD = 30
SUBAGENT_MODEL_CALLS_PER_RUN = 6
SUBAGENT_TOOL_CALLS_PER_RUN = 8
# Specialists start fresh each time, so they get this many recent turns of the conversation.
DELEGATE_TURNS = 6
# The pathological ceiling: every call times out, on every model, on every attempt.
TURN_BUDGET_SECONDS = 1800


def worst_case_seconds() -> int:
    per_call = (1 + MODEL_MAX_RETRIES) * len(MODEL_CHAIN) * MODEL_TIMEOUT_SECONDS
    # Each supervisor delegation runs a whole subagent, so its calls multiply in.
    calls = SUPERVISOR_MODEL_CALLS_PER_RUN + SUPERVISOR_TOOL_CALLS_PER_RUN * SUBAGENT_MODEL_CALLS_PER_RUN
    return calls * per_call

# Release gates for eval experiments.
SAFETY_MIN = 1.0
DETERMINISTIC_MIN = 0.95
ROUTING_MIN = 0.95
JUDGE_MAX_DROP = 0.0
EVAL_REPETITIONS = 3
# A different model family from the primary agent, so the judge is not grading itself.
JUDGE_MODEL = ModelSpec("anthropic:claude-sonnet-4-6", "ANTHROPIC_API_KEY")

# Online monitoring on sampled production traces.
ONLINE_SAMPLE_RATE = 0.1
ALERT_P99_LATENCY_SECONDS = 30
ALERT_ERROR_RATE = 0.02
ALERT_FALLBACK_RATE = 0.10
ALERT_LIMIT_HIT_RATE = 0.05

# Business assumptions: stated on screen, never presented as measured data.
ASSUMED_CONVERSION_RATE = 0.10
ASSUMED_MINUTES_PER_MANUAL_REFUND = 6
ASSUMED_SUPPORT_COST_PER_HOUR = 30

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from decimal import Decimal


def valid_discount(value: Decimal) -> Decimal:
    if not isinstance(value, Decimal) or not Decimal("0") <= value < Decimal("1"):
        raise ValueError("discount must be a Decimal from 0 up to but not including 1")
    return value


# Chinook has no album price, so completion needs an explicit discount to be worth taking.
COMPLETION_DISCOUNT = valid_discount(Decimal("0.20"))


# Apple FairPlay DRM: these formats only play on Apple devices.
PROTECTED_FORMATS = frozenset(
    {"Protected AAC audio file", "Protected MPEG-4 video file"}
)
VIDEO_FORMATS = frozenset({"Protected MPEG-4 video file"})

# Every format Chinook ships. A test keeps this in step with the database.
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


@dataclass(frozen=True)
class ModelSpec:
    name: str
    api_key_env: str | None = None
    options: Mapping[str, Any] | None = None


# Tried in order when a model call fails. Add a provider by appending a spec;
# use a second key from a provider already listed by naming its own api_key_env.
MODEL_CHAIN = (
    ModelSpec("openai:gpt-5.6-luna", "OPENAI_API_KEY", {"use_responses_api": True}),
    ModelSpec("anthropic:claude-sonnet-4-6", "ANTHROPIC_API_KEY"),
)


# Cost ceiling: a confused agent stops here instead of billing indefinitely.
# Per run is one user message; per thread is the whole conversation.
MODEL_CALLS_PER_RUN = 8
MODEL_CALLS_PER_THREAD = 40
TOOL_CALLS_PER_RUN = 12
TOOL_CALLS_PER_THREAD = 60


# One model call is allowed this long; retries and the fallback chain multiply it.
MODEL_TIMEOUT_SECONDS = 15
MODEL_MAX_RETRIES = 1
# No single turn may take longer than this, however the failures line up.
TURN_BUDGET_SECONDS = 600


def worst_case_seconds() -> int:
    """Every model call timing out, on every model, on every attempt."""
    per_call = (1 + MODEL_MAX_RETRIES) * len(MODEL_CHAIN)
    return MODEL_CALLS_PER_RUN * per_call * MODEL_TIMEOUT_SECONDS

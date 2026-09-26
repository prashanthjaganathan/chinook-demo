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


MAX_SEARCH_TEXT = 100
MAX_SEARCH_RESULTS = 50
MAX_REASON = 500

INVOICE_NOT_FOUND = "Invoice not found on this account."
NO_IDENTITY = "I cannot see who is signed in, so I cannot open this account."
NO_PURCHASES = "There are no purchases on this account yet."


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
# Median call is ~1.6s but the tail reaches ~9s, so the timeout sits well above it.
MODEL_TIMEOUT_SECONDS = 30
MODEL_MAX_RETRIES = 1

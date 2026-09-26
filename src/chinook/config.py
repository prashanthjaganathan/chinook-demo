from decimal import Decimal


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

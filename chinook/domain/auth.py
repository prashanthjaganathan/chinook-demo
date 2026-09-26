import re
from dataclasses import dataclass, field

from chinook.foundation import config
from chinook.helpers import otp
from chinook.helpers.catalog import digits_only

PHONE_PATTERN = re.compile(r"\+?\d[\d\s().-]{8,}\d")


def normalize(text) -> str | None:
    digits = digits_only(text)
    return digits if 10 <= len(digits) <= 15 else None


def extract_phone(text: str, llm_fallback=None) -> str | None:
    for match in PHONE_PATTERN.findall(text or ""):
        if phone := normalize(match):
            return phone
    # The model only helps with messy text, and its answer is validated like user input.
    return normalize(llm_fallback(text)) if llm_fallback else None


@dataclass(frozen=True)
class Decision:
    reply: str | None
    updates: dict = field(default_factory=dict)
    verified: int | None = None
    send_code_to: str | None = None


def failed(attempts: int, reply: str) -> Decision:
    attempts += 1
    if attempts >= config.AUTH_MAX_ATTEMPTS:
        return Decision(config.AUTH_LOCKED, {"auth_stage": "locked", "auth_attempts": attempts})
    return Decision(reply, {"auth_attempts": attempts})


def next_step(state: dict, message: str, lookup, extract=extract_phone, check=otp.check_code) -> Decision:
    stage, attempts = state.get("auth_stage"), state.get("auth_attempts") or 0
    if stage == "locked":
        return Decision(config.AUTH_LOCKED)
    if stage is None:
        return Decision(config.ASK_PHONE, {"auth_stage": "need_phone", "pending_question": message})
    if stage == "need_phone":
        phone = extract(message)
        if phone is None:
            return failed(attempts, config.NO_PHONE)
        customer_id = lookup(phone)
        updates = {"auth_stage": "awaiting_code", "pending_phone": phone, "pending_customer_id": customer_id}
        return Decision(config.CODE_SENT, updates, send_code_to=phone if customer_id else None)
    customer_id = state.get("pending_customer_id")
    if customer_id and check(state.get("pending_phone"), message.strip()):
        cleared = {"auth_stage": "verified", "verified_customer_id": customer_id,
                   "pending_phone": None, "pending_customer_id": None, "auth_attempts": 0}
        return Decision(None, cleared, verified=customer_id)
    return failed(attempts, config.BAD_CODE)

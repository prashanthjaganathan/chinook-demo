import pytest

from chinook.domain import auth
from chinook.foundation import config
from chinook.helpers import otp

AARON = "+1 (204) 452-6452"


@pytest.mark.parametrize("text", [f"my number is {AARON}", "204-452-6452", "call 2044526452 please"])
def test_phone_formats_are_found_by_regex(text):
    assert auth.extract_phone(text).endswith("2044526452")


def test_the_llm_is_called_only_when_regex_misses_and_its_answer_is_revalidated():
    calls = []
    llm = lambda text: calls.append(text) or "(204) 452 6452"

    assert auth.extract_phone("204-452-6452", llm) == "2044526452" and calls == []
    assert auth.extract_phone("it's two oh four...", llm) == "2044526452" and len(calls) == 1
    assert auth.extract_phone("hello", lambda t: "call me maybe") is None
    assert auth.extract_phone("hello", lambda t: "1" * 20) is None
    assert auth.extract_phone("no digits here") is None


@pytest.mark.parametrize("code, ok", [("1234", True), ("12345678", True), ("123", False),
                                       ("123456789", False), ("12ab", False), ("", False)])
def test_otp_accepts_only_four_to_eight_digits(code, ok):
    assert otp.check_code(AARON, code) is ok


def step(state, message, lookup=lambda phone: 32):
    decision = auth.next_step(state, message, lookup)
    return {**state, **decision.updates}, decision


def test_the_happy_path_verifies_and_keeps_the_question():
    state, d = step({}, "what am I closest to finishing?")
    assert d.reply == config.ASK_PHONE
    state, d = step(state, AARON)
    assert d.reply == config.CODE_SENT and d.send_code_to
    state, d = step(state, "123456")

    assert d.verified == 32 and state["verified_customer_id"] == 32
    assert state["pending_question"] == "what am I closest to finishing?"


def test_an_unknown_phone_gets_the_identical_reply_and_no_code():
    state, _ = step({}, "hi")
    _, known = step(state, AARON)
    _, unknown = step(state, "+1 (999) 000-0000", lookup=lambda phone: None)

    assert known.reply == unknown.reply == config.CODE_SENT
    assert unknown.send_code_to is None


def test_an_unknown_phone_can_never_verify():
    state, _ = step({}, "hi")
    state, _ = step(state, "+1 (999) 000-0000", lookup=lambda phone: None)
    _, d = step(state, "123456", lookup=lambda phone: None)

    assert d.verified is None and d.reply == config.BAD_CODE


def test_three_failures_lock_the_thread_for_good():
    state, _ = step({}, "hi")
    state, _ = step(state, AARON)
    for _ in range(2):
        state, d = step(state, "bad")
        assert d.reply == config.BAD_CODE
    state, d = step(state, "bad")
    assert d.reply == config.AUTH_LOCKED
    _, d = step(state, "123456")

    assert d.reply == config.AUTH_LOCKED and d.verified is None

"""The one file to swap for Twilio or a real auth provider."""

import logging

from chinook import config

log = logging.getLogger(__name__)


def send_code(phone: str) -> None:
    log.info("would send a one-time code to a number ending %s", phone[-4:])


def check_code(phone: str, code: str) -> bool:
    low, high = config.OTP_LENGTH_RANGE
    return isinstance(code, str) and code.isdigit() and low <= len(code) <= high

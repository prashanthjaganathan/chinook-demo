import sqlite3

from chinook_agent import config
from chinook_agent.prompt import SYSTEM_PROMPT, formats


def test_config_lists_exactly_the_formats_in_the_database(chinook_db):
    connection = sqlite3.connect(chinook_db)
    try:
        in_database = {row[0] for row in connection.execute("SELECT Name FROM MediaType")}
    finally:
        connection.close()

    assert set(config.MEDIA_TYPES) == in_database


def test_every_format_appears_in_the_prompt():
    for media_type in config.MEDIA_TYPES:
        assert media_type in SYSTEM_PROMPT


def test_the_table_splits_formats_the_way_the_code_does():
    playable, locked = formats(True), formats(False)

    for media_type in config.MEDIA_TYPES:
        side = playable if config.plays_anywhere(media_type) else locked

        assert media_type in side


def test_protected_formats_are_never_described_as_playing_anywhere():
    playable = formats(True)

    assert "Protected AAC audio file" not in playable
    assert "Protected MPEG-4 video file" not in playable


def test_prompt_states_the_rules_workflow_b_depends_on():
    # The prompt is hard-wrapped, so compare against a single-spaced copy.
    flat = " ".join(SYSTEM_PROMPT.split())

    for rule in (
        "do not blame the format",
        "can only be refunded, never replaced",
        "exclude_owned",
        "cost the same as the original",
        "never say a refund or replacement has been made",
        "the request did not happen",
    ):
        assert rule in flat

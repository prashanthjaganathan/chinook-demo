import hashlib
from pathlib import Path

import pytest

DB_PATH = Path(__file__).resolve().parents[1] / "data" / "chinook.db"


def _digest() -> str | None:
    return hashlib.sha256(DB_PATH.read_bytes()).hexdigest() if DB_PATH.exists() else None


@pytest.fixture(scope="session")
def chinook_db() -> Path:
    if not DB_PATH.exists():
        pytest.fail("data/chinook.db is missing. Run scripts/build_db.sh")
    return DB_PATH


@pytest.fixture(scope="session", autouse=True)
def chinook_file_is_unchanged():
    before = _digest()
    yield
    assert _digest() == before, "the test suite modified data/chinook.db"

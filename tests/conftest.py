from pathlib import Path

import pytest

DB_PATH = Path(__file__).resolve().parents[1] / "data" / "chinook.db"


@pytest.fixture(scope="session")
def chinook_db() -> Path:
    if not DB_PATH.exists():
        pytest.fail("data/chinook.db is missing. Run scripts/build_db.sh")
    return DB_PATH

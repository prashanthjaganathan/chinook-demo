# Chinook Support Agent

A customer support agent for a digital music store, built on LangChain and Chinook.

## Setup

Requires [uv](https://docs.astral.sh/uv/) and `sqlite3`. Python 3.12 is installed by uv if missing.

```bash
uv sync                  # creates .venv, installs deps from uv.lock
./scripts/build_db.sh    # verifies the Chinook v1.4.5 hash, builds data/chinook.db
uv run pytest            # 4 passed
```

## Commands

```bash
uv run pytest            # run tests
uv run pytest -q         # quiet
uv run python -c "..."   # run anything inside the project env
```

`uv run` uses `.venv` without activating it. To activate instead:

```bash
source .venv/bin/activate
```

## Notes

- If a conda env is active, `uv run` ignores it and warns. That is expected.
- Plain `uv pip install <pkg>` can target the wrong environment. Use `uv add <pkg>`,
  which updates `pyproject.toml` and `uv.lock` together.
- `data/chinook.db` is a build artifact and is not tracked. `uv.lock` is tracked.

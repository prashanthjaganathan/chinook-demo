import hashlib
import re

import langsmith
from langsmith import Client
from langsmith.anonymizer import create_anonymizer

from chinook import catalog, config, prompts

PHONE = re.compile(r"\+?\d[\d\s().-]{8,}\d")
EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
NAMES_SQL = "SELECT FirstName AS first, LastName AS last FROM Customer"


def names_pattern() -> re.Pattern:
    names = {part for row in catalog.query(NAMES_SQL, ()) for part in (row["first"], row["last"])}
    longest_first = sorted((n for n in names if len(n) > 2), key=len, reverse=True)
    return re.compile(r"\b(" + "|".join(map(re.escape, longest_first)) + r")\b")


def mask_text(text: str, names: re.Pattern | None = None) -> str:
    text = EMAIL.sub("<email>", PHONE.sub("<phone>", text))
    return (names or names_pattern()).sub("<name>", text)


def masking_client() -> Client:
    names = names_pattern()
    return Client(anonymizer=create_anonymizer(lambda text, path: mask_text(text, names)))


def enable_masking() -> None:
    # Every LangChain trace in this process goes through the masking client, Studio included.
    langsmith.configure(client=masking_client())


def prompt_version(specs) -> str:
    text = prompts.supervisor_prompt(specs) + "".join(spec.prompt for spec in specs)
    return hashlib.sha256(text.encode()).hexdigest()[:12]


def run_metadata(specs, auth_mode: str, thread_id: str, subagents=(), models_used=(), case_id=None) -> dict:
    primary = config.MODEL_CHAIN[0].name.split(":", 1)[1]
    return {
        "auth_mode": auth_mode,
        "thread_id": thread_id,
        "subagents": sorted(subagents),
        "prompt_version": prompt_version(specs),
        "models": sorted(models_used),
        "fallback_used": any(primary not in model for model in models_used),
        "case_id": case_id,
    }

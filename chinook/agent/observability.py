import hashlib
import re

import langsmith
from langsmith import Client
from langsmith.anonymizer import create_anonymizer

from chinook.agent import prompts
from chinook.foundation import config
from chinook.helpers import catalog

PHONE = re.compile(r"\+?\d[\d\s().-]{8,}\d")
EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
NAMES_SQL = "SELECT FirstName AS first, LastName AS last FROM Customer"


def enable_masking() -> None:
    """Masks phones, emails, and customer names in every LangChain trace in this process, Studio included."""
    names = {part for row in catalog.query(NAMES_SQL, ()) for part in (row["first"], row["last"])}
    # Longest first, so "Mary Ann" is masked before "Mary"; one compiled pattern keeps it fast.
    longest_first = sorted((n for n in names if len(n) > 2), key=len, reverse=True)
    name = re.compile(r"\b(" + "|".join(map(re.escape, longest_first)) + r")\b")

    def mask(text: str, path) -> str:
        return name.sub("<name>", EMAIL.sub("<email>", PHONE.sub("<phone>", text)))

    langsmith.configure(client=Client(anonymizer=create_anonymizer(mask)))


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

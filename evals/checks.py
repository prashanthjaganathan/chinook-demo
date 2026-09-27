"""Deterministic evaluators: each returns a 0/1 score and a comment saying why."""
import re
from decimal import Decimal

PRICE = re.compile(r"\$\s?(\d+(?:\.\d{2})?)")
AMOUNT = re.compile(r"\d+\.\d{2}")


def matches(got, want) -> bool:
    if isinstance(want, dict) and set(want) == {"contains"}:
        return want["contains"].lower() in str(got or "").lower()
    if isinstance(want, dict):
        return isinstance(got, dict) and all(matches(got.get(k), v) for k, v in want.items())
    if isinstance(want, list):
        return isinstance(got, list) and all(any(matches(g, w) for g in got) for w in want)
    if want is None:
        return got in (None, "", [], {})
    return got == want


def right_tools(outputs: dict, reference_outputs: dict) -> dict:
    called = [call["name"] for call in outputs["calls"]]
    problems = []
    if "exactly" in reference_outputs and set(called) != set(reference_outputs["exactly"]):
        problems.append(f"expected {sorted(reference_outputs['exactly'])}")
    problems += [f"missing {t}" for t in reference_outputs.get("must_call", []) if t not in called]
    problems += [f"should not call {t}" for t in reference_outputs.get("must_not_call", []) if t in called]
    return {"key": "right_tools", "score": int(not problems),
            "comment": f"called {called}; " + "; ".join(problems) if problems else f"called {called}"}


def right_args(outputs: dict, reference_outputs: dict) -> dict:
    wanted = reference_outputs.get("args")
    if not wanted:
        return {"key": "right_args", "score": None}
    for tool, expected in wanted.items():
        call = next((c for c in outputs["calls"] if c["name"] == tool), None)
        if call is None or not matches(call["args"], expected):
            return {"key": "right_args", "score": 0,
                    "comment": f"{tool} got {call['args'] if call else 'no call'}, wanted {expected}"}
    return {"key": "right_args", "score": 1}


def clarifies(outputs: dict, reference_outputs: dict) -> dict:
    """A vague message gets a question back, and an off-topic one gets no answer."""
    reply = outputs["reply"].lower()
    if reference_outputs.get("asks") and "?" not in reply:
        return {"key": "clarifies", "score": 0, "comment": "no question asked"}
    answered = [text for text in reference_outputs.get("reply_excludes", []) if text in reply]
    if answered:
        return {"key": "clarifies", "score": 0, "comment": f"answered off-topic: {answered}"}
    wanted = reference_outputs.get("asks") or reference_outputs.get("reply_excludes")
    return {"key": "clarifies", "score": 1 if wanted else None}


def prices_sourced(outputs: dict) -> dict:
    quoted = {Decimal(p) for p in PRICE.findall(outputs["reply"])}
    sourced = {Decimal(a) for a in AMOUNT.findall(outputs["tool_text"])}
    invented = sorted(str(p) for p in quoted - sourced)
    return {"key": "prices_sourced", "score": int(not invented),
            "comment": f"not from any tool: {invented}" if invented else "all prices sourced"}

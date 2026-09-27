"""Push a suite's dataset (named by a hash of its cases) and run an experiment on it.

    uv run python -m evals.run sales --prefix baseline
"""
import argparse
import hashlib
import json

from langsmith import Client

from chinook.agent import observability
from chinook.agent.team import SUBAGENTS
from chinook.foundation import config
from evals import cases, checks, targets

SUITES = {
    "supervisor": (cases.supervisor, targets.supervisor_turn,
                   [checks.right_tools, checks.right_args, checks.clarifies, checks.prices_sourced]),
    "sales": (cases.sales, targets.sales_first_decision, [checks.right_tools, checks.right_args]),
    "support": (cases.support, targets.support_until_pause, [checks.right_tools, checks.right_args]),
}


def push(client: Client, suite: str, examples: list[dict]) -> str:
    # Same cases, same name; any change to a case makes a new dataset, so old scores stay comparable.
    digest = hashlib.sha256(json.dumps(examples, sort_keys=True, default=str).encode()).hexdigest()[:8]
    name = f"chinook-{suite}-{digest}"
    if not client.has_dataset(dataset_name=name):
        dataset = client.create_dataset(dataset_name=name, description=f"{suite} model decisions")
        client.create_examples(dataset_id=dataset.id, examples=examples)
    return name


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("suite", choices=SUITES)
    parser.add_argument("--prefix", default="baseline")
    args = parser.parse_args()

    build, target, evaluators = SUITES[args.suite]
    client = Client()
    client.evaluate(
        target, data=push(client, args.suite, build()), evaluators=evaluators,
        experiment_prefix=f"{args.suite}-{args.prefix}",
        num_repetitions=config.EVAL_REPETITIONS, max_concurrency=4,
        metadata={"prompt_version": observability.prompt_version(SUBAGENTS),
                  "model": config.MODEL_CHAIN[0].name},
    )


if __name__ == "__main__":
    main()

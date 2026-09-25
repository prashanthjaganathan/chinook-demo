import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_graph_entrypoint_imports():
    from chinook_agent.agent import graph

    assert callable(graph)


def test_langgraph_config_points_at_a_real_entrypoint():
    config = json.loads((ROOT / "langgraph.json").read_text())
    module_path, _, attribute = config["graphs"]["support"].partition(":")

    assert (ROOT / module_path).exists()
    assert attribute == "graph"
    assert config["env"] == ".env"


def test_env_example_lists_every_key_the_agent_needs():
    example = (ROOT / ".env.example").read_text()

    for key in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "LANGSMITH_API_KEY"):
        assert key in example


def test_real_env_file_is_not_committed():
    import subprocess

    tracked = subprocess.run(
        ["git", "ls-files", ".env"], cwd=ROOT, capture_output=True, text=True
    ).stdout

    assert tracked.strip() == ""

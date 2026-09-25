import pytest

from chinook_agent import config, models
from chinook_agent.tools import TOOLS


def test_chain_starts_with_openai_and_falls_back_to_anthropic():
    providers = [spec.name.split(":")[0] for spec in config.MODEL_CHAIN]

    assert providers[:2] == ["openai", "anthropic"]


def test_every_spec_names_its_provider():
    for spec in config.MODEL_CHAIN:
        provider, separator, model = spec.name.partition(":")

        assert separator and provider and model


def test_chain_has_at_least_one_fallback():
    assert len(config.MODEL_CHAIN) >= 2


def test_specs_are_immutable():
    with pytest.raises(Exception):
        config.MODEL_CHAIN[0].name = "something-else"


def test_a_named_api_key_env_must_be_set(monkeypatch):
    monkeypatch.delenv("SPARE_OPENAI_KEY", raising=False)
    spec = config.ModelSpec("openai:gpt-5.6", api_key_env="SPARE_OPENAI_KEY")

    with pytest.raises(ValueError, match="SPARE_OPENAI_KEY"):
        models.build(spec)


def test_a_second_key_from_the_same_provider_is_used(monkeypatch):
    monkeypatch.setenv("SPARE_OPENAI_KEY", "sk-spare-key")
    spec = config.ModelSpec("openai:gpt-5.6", api_key_env="SPARE_OPENAI_KEY")

    model = models.build(spec)

    assert model.openai_api_key.get_secret_value() == "sk-spare-key"


def test_a_spec_without_a_named_env_uses_the_provider_default(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-default-key")

    model = models.build(config.ModelSpec("openai:gpt-5.6"))

    assert model.openai_api_key.get_secret_value() == "sk-default-key"


def test_a_third_provider_can_be_added_without_touching_the_builder(monkeypatch):
    monkeypatch.setenv("GOOGLE_API_KEY", "gk-test")
    chain = config.MODEL_CHAIN + (config.ModelSpec("google_genai:gemini-3.7-flash"),)

    assert [spec.name for spec in chain][-1] == "google_genai:gemini-3.7-flash"
    assert chain[-1].api_key_env is None


def test_fallbacks_are_everything_after_the_primary(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-x")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-y")

    assert len(models.fallbacks()) == len(config.MODEL_CHAIN) - 1
    assert models.primary().model_name.startswith("gpt")


def test_per_spec_options_reach_the_model(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    spec = config.ModelSpec("openai:gpt-5.6-luna", options={"use_responses_api": True})

    assert models.build(spec).use_responses_api is True


def test_the_openai_spec_uses_the_responses_api():
    # Without it, binding tools returns 400 on /v1/chat/completions.
    openai_spec = next(s for s in config.MODEL_CHAIN if s.name.startswith("openai:"))

    assert (openai_spec.options or {}).get("use_responses_api") is True


@pytest.mark.live
@pytest.mark.parametrize(
    "spec", config.MODEL_CHAIN, ids=[spec.name for spec in config.MODEL_CHAIN]
)
def test_every_model_in_the_chain_can_call_our_tools(spec):
    reply = models.build(spec).bind_tools(TOOLS).invoke("How many tracks do I own?")

    assert [call["name"] for call in reply.tool_calls] == ["get_my_library"]

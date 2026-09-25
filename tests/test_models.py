import pytest

from chinook_agent import config, models


def test_chain_starts_with_openai_and_falls_back_to_anthropic():
    assert [spec.name for spec in config.MODEL_CHAIN] == [
        "openai:gpt-5.6",
        "anthropic:claude-sonnet-5",
    ]


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

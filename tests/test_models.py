import pytest

from chinook import config, models


@pytest.fixture
def keys(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")


def test_chain_starts_with_openai_and_falls_back_to_anthropic():
    assert [s.name.split(":")[0] for s in config.MODEL_CHAIN][:2] == ["openai", "anthropic"]


def test_a_named_key_must_be_set(monkeypatch):
    monkeypatch.delenv("SPARE_KEY", raising=False)

    with pytest.raises(ValueError, match="SPARE_KEY"):
        models.build(config.ModelSpec("openai:gpt-5.6-luna", "SPARE_KEY"))


def test_a_second_key_from_the_same_provider_is_used(monkeypatch):
    monkeypatch.setenv("SPARE_KEY", "sk-spare")
    model = models.build(config.ModelSpec("openai:gpt-5.6-luna", "SPARE_KEY"))

    assert model.openai_api_key.get_secret_value() == "sk-spare"


def test_every_model_has_a_timeout_and_no_sdk_retries(keys):
    for spec in config.MODEL_CHAIN:
        model = models.build(spec)
        timeout = getattr(model, "request_timeout", None) or getattr(model, "default_request_timeout", None)

        assert model.max_retries == 0
        assert timeout == config.MODEL_TIMEOUT_SECONDS


def test_openai_uses_the_responses_api(keys):
    assert models.primary().use_responses_api is True
    assert len(models.fallbacks()) == len(config.MODEL_CHAIN) - 1

import os

from langchain.chat_models import init_chat_model
from langchain_core.language_models import BaseChatModel

from chinook import config


def build(spec: config.ModelSpec) -> BaseChatModel:
    # Retries live in middleware, so the provider SDK does not add its own.
    options = {"timeout": config.MODEL_TIMEOUT_SECONDS, "max_retries": 0, **(spec.options or {})}
    if spec.api_key_env:
        key = os.environ.get(spec.api_key_env)
        if not key:
            raise ValueError(f"{spec.api_key_env} is not set")
        options["api_key"] = key
    return init_chat_model(spec.name, **options)


def primary() -> BaseChatModel:
    return build(config.MODEL_CHAIN[0])


def fallbacks() -> list[BaseChatModel]:
    return [build(spec) for spec in config.MODEL_CHAIN[1:]]

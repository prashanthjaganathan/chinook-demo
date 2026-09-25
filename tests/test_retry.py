from langchain.agents import create_agent
from langchain.agents.middleware import ModelFallbackMiddleware, ModelRetryMiddleware
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from chinook_agent import agent, config, models
from chinook_agent.middleware import MODEL_UNAVAILABLE, model_failure

ATTEMPTS = []


def a_model(name: str, works: bool) -> BaseChatModel:
    class Fake(BaseChatModel):
        @property
        def _llm_type(self) -> str:
            return name

        def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
            ATTEMPTS.append(name)
            if not works:
                raise RuntimeError(f"{name} is down")
            return ChatResult(
                generations=[ChatGeneration(message=AIMessage(f"{name} answered"))]
            )

        def bind_tools(self, tools, **kwargs):
            return self

    return Fake()


def run(primary, spare, retries=config.MODEL_MAX_RETRIES):
    ATTEMPTS.clear()
    graph = create_agent(
        model=primary,
        tools=[],
        middleware=[
            ModelRetryMiddleware(
                max_retries=retries, initial_delay=0, on_failure=model_failure
            ),
            ModelFallbackMiddleware(spare),
        ],
    )
    answer = graph.invoke({"messages": [{"role": "user", "content": "hi"}]})
    return answer["messages"][-1].text, list(ATTEMPTS)


def test_the_primary_is_used_when_it_works():
    answer, attempts = run(a_model("primary", True), a_model("spare", True))

    assert answer == "primary answered"
    assert attempts == ["primary"]


def test_the_fallback_answers_when_the_primary_fails():
    answer, attempts = run(a_model("primary", False), a_model("spare", True))

    assert answer == "spare answered"
    assert attempts == ["primary", "spare"]


def test_retry_wraps_the_whole_chain_not_just_the_primary():
    # Retry outside fallback means one attempt walks primary then spare.
    _, attempts = run(a_model("primary", False), a_model("spare", False), retries=1)

    assert attempts == ["primary", "spare", "primary", "spare"]


def test_more_retries_walk_the_chain_more_times():
    _, attempts = run(a_model("primary", False), a_model("spare", False), retries=2)

    assert attempts.count("primary") == 3
    assert attempts.count("spare") == 3


def test_both_models_down_returns_a_safe_message():
    answer, _ = run(a_model("primary", False), a_model("spare", False))

    assert answer == MODEL_UNAVAILABLE


def test_the_failure_message_never_repeats_the_providers_words():
    message = model_failure(RuntimeError("invalid x-api-key sk-abc123 at api.openai.com"))

    for secret in ("sk-abc123", "api.openai.com", "x-api-key", "Traceback"):
        assert secret not in message


def test_retry_is_listed_before_fallback():
    names = [type(item).__name__ for item in agent.middleware_stack(spares=[a_model("s", True)])]

    assert names.index("ModelRetryMiddleware") < names.index("ModelFallbackMiddleware")


def test_every_model_gets_a_timeout(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")

    for spec in config.MODEL_CHAIN:
        built = models.build(spec)

        assert built.max_retries == 0
        # Providers store it under different names.
        timeout = (
            getattr(built, "request_timeout", None)
            or getattr(built, "default_request_timeout", None)
            or getattr(built, "timeout", None)
        )

        assert timeout == config.MODEL_TIMEOUT_SECONDS


def test_worst_case_turn_time_is_within_budget():
    assert config.worst_case_seconds() <= config.TURN_BUDGET_SECONDS


def test_the_worst_case_accounts_for_every_multiplier():
    expected = (
        config.MODEL_CALLS_PER_RUN
        * (1 + config.MODEL_MAX_RETRIES)
        * len(config.MODEL_CHAIN)
        * config.MODEL_TIMEOUT_SECONDS
    )

    assert config.worst_case_seconds() == expected


def test_the_timeout_leaves_room_over_real_latency():
    # Measured tool-bound calls run 1.3s to 2.6s on both providers.
    assert config.MODEL_TIMEOUT_SECONDS >= 10

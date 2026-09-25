from langchain.agents import create_agent
from langchain.agents.middleware import ModelFallbackMiddleware
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from chinook_agent import models


class BrokenModel(BaseChatModel):
    @property
    def _llm_type(self) -> str:
        return "broken"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        raise RuntimeError("provider is down")

    def bind_tools(self, tools, **kwargs):
        return self


class CannedModel(BaseChatModel):
    def __init__(self, reply: str):
        super().__init__()
        self._reply = reply

    @property
    def _llm_type(self) -> str:
        return "canned"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        return ChatResult(
            generations=[ChatGeneration(message=AIMessage(content=self._reply))]
        )

    def bind_tools(self, tools, **kwargs):
        return self


def run(primary, *spares) -> str:
    graph = create_agent(
        model=primary,
        tools=[],
        middleware=[ModelFallbackMiddleware(*spares)] if spares else [],
    )
    result = graph.invoke({"messages": [{"role": "user", "content": "hello"}]})
    return result["messages"][-1].content


def test_the_second_provider_answers_when_the_first_is_down():
    assert run(BrokenModel(), CannedModel("second")) == "second"


def test_a_third_provider_answers_when_the_first_two_are_down():
    assert run(BrokenModel(), BrokenModel(), CannedModel("third")) == "third"


def test_the_primary_is_used_when_it_works():
    assert run(CannedModel("primary"), CannedModel("second")) == "primary"


def test_every_model_down_raises_rather_than_answering_silently():
    try:
        run(BrokenModel(), BrokenModel())
    except Exception as error:
        assert "down" in str(error)
    else:
        raise AssertionError("a fully failed chain must not return an answer")


def test_the_configured_chain_builds_real_model_instances(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")

    spares = models.fallbacks()

    assert spares and all(isinstance(model, BaseChatModel) for model in spares)
    assert ModelFallbackMiddleware(*spares) is not None

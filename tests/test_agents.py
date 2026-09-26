import os

import pytest
from helpers import call, once_then, tool_results

from chinook import agents, config, prompts
from chinook.context import CustomerContext

live = pytest.mark.skipif(not os.getenv("OPENAI_API_KEY"), reason="needs a real key")


def ask(spec_name, text, customer_id, model=None):
    agent = agents.build_subagent(agents.spec_named(spec_name), model=model)
    return agent.invoke({"messages": [{"role": "user", "content": text}]},
                        context=CustomerContext(customer_id=customer_id))


def test_the_registry_names_both_specialists():
    assert [s.name for s in agents.SUBAGENTS] == ["music_recommendation", "invoice_support"]


def test_music_recommendation_uses_the_engine_but_not_invoices():
    names = {t.name for t in agents.spec_named("music_recommendation").tools}

    assert "recommend_engine" in names and "get_invoice" not in names


def test_a_subagent_runs_its_tools_with_the_given_customer():
    result = ask("music_recommendation", "what should I finish?", 48,
                 model=once_then(call("recommend_engine", {"mode": "complete_album"})))

    assert '"In Step"' in tool_results(result["messages"])[0].content or "In Step" in str(
        tool_results(result["messages"])[0].content)


def test_the_format_table_in_the_prompt_comes_from_config():
    playable, locked = prompts.formats(True), prompts.formats(False)

    for media_type in config.MEDIA_TYPES:
        assert media_type in (playable if config.plays_anywhere(media_type) else locked)
    assert "Protected AAC audio file" not in playable


@pytest.mark.live
@live
def test_music_recommendation_finds_in_step_for_customer_48():
    answer = ask("music_recommendation", "What am I closest to finishing?", 48)["messages"][-1].text

    assert "In Step" in answer and "4.75" in answer


@pytest.mark.live
@live
def test_invoice_support_diagnoses_protected_aac_on_android():
    answer = ask("invoice_support", "Midnight will not play on my Android phone.", 54)["messages"][-1].text

    assert "refund" in answer.lower() and ("drm" in answer.lower() or "protected" in answer.lower())


@pytest.mark.live
@live
def test_invoice_support_does_not_blame_the_format_for_an_mp3():
    answer = ask("invoice_support", "Someday Never Comes will not play on my Android.", 54)["messages"][-1].text
    lower = answer.lower()

    assert "fairplay" not in lower
    assert "only play on apple" not in lower


@pytest.mark.live
@live
def test_invoice_support_offers_only_a_refund_for_video():
    answer = ask("invoice_support", "A TV episode I bought won't play on my Android tablet. Can I swap it?", 51)

    assert "refund" in answer["messages"][-1].text.lower()

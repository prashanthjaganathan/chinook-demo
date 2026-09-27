from chinook.domain import refunds
from evals import cases, checks


def test_every_suite_builds_with_unique_case_names():
    for build in (cases.supervisor, cases.sales, cases.support):
        names = [example["metadata"]["case"] for example in build()]
        assert names and len(names) == len(set(names))


def test_support_refs_point_at_the_customers_real_purchases():
    for example in cases.support():
        for args in example["outputs"].get("args", {}).values():
            assert refunds.purchase_for_ref(cases.SUPPORT_CUSTOMER, args["purchase_ref"])


def test_matching_rules():
    assert checks.matches("AC/DC please", {"contains": "ac/dc"})
    assert checks.matches(None, None) and checks.matches("", None) and not checks.matches("jazz", None)
    assert checks.matches({"artists": ["Miles Davis", "Coltrane"]}, {"artists": [{"contains": "miles"}]})
    assert not checks.matches({"device": "apple"}, {"device": "other"})


def test_right_tools_explains_what_went_wrong():
    outputs = {"calls": [{"name": "request_refund", "args": {}}]}

    passed = checks.right_tools(outputs, {"must_call": ["request_refund"]})
    failed = checks.right_tools(outputs, {"must_not_call": ["request_refund"]})

    assert passed["score"] == 1
    assert failed["score"] == 0 and "should not call request_refund" in failed["comment"]


def test_cases_without_arg_expectations_are_left_out_of_the_average():
    assert checks.right_args({"calls": []}, {"exactly": []})["score"] is None


def test_prices_must_come_from_a_tool_and_whole_dollars_match_cents():
    tools = '{"final_price": "5.00"}'
    assert checks.prices_sourced({"reply": "That's $5.", "tool_text": tools})["score"] == 1
    invented = checks.prices_sourced({"reply": "Only $3.99!", "tool_text": tools})
    assert invented["score"] == 0 and "3.99" in invented["comment"]


def test_clarifies_needs_a_question_and_no_off_topic_answer():
    assert checks.clarifies({"reply": "Happy to help! Music or a purchase?"}, {"asks": True})["score"] == 1
    assert checks.clarifies({"reply": "Sure."}, {"asks": True})["score"] == 0
    assert checks.clarifies({"reply": "In 2024, Wimbledon was won by…"},
                            {"reply_excludes": ["wimbledon was"]})["score"] == 0
    assert checks.clarifies({"reply": "Hi"}, {"exactly": []})["score"] is None

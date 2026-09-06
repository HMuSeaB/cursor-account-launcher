"""usage-summary 汇总：3.18 Plan & Usage 文案仍要能读出百分比。"""

from launcher.cursor_usage import _parse_included_pcts, summarize_usage


def test_parse_included_pcts_old_copy():
    total, api = _parse_included_pcts(
        {
            "autoModelSelectedDisplayMessage": "You've used 12.5% of your included total usage",
            "namedModelSelectedDisplayMessage": "You've used 3% of your included API usage",
        }
    )
    assert total == 12.5
    assert api == 3.0


def test_parse_included_pcts_318_plan_usage_copy():
    total, api = _parse_included_pcts(
        {
            "autoModelSelectedDisplayMessage": "You've used 7% of your included Cursor Models",
            "namedModelSelectedDisplayMessage": "You've used 0% of your included Other Models",
        }
    )
    assert total == 7.0
    assert api == 0.0


def test_summarize_falls_back_to_318_messages_when_plan_pcts_missing():
    snap = summarize_usage(
        {
            "membershipType": "free",
            "autoModelSelectedDisplayMessage": "You've used 7% of your included Cursor Models",
            "namedModelSelectedDisplayMessage": "You've used 0% of your included Other Models",
            "individualUsage": {"plan": {}},
        }
    )
    assert snap["membershipType"] == "free"
    assert snap["autoPercentUsed"] == 7.0
    assert snap["apiPercentUsed"] == 0.0

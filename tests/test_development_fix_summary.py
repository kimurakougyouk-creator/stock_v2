from ai_asset_platform.developer.fix_reason import create_fix_reason
from ai_asset_platform.developer.fix_report import create_fix_report
from ai_asset_platform.developer.fix_summary import create_fix_summary


def test_create_fix_summary():
    reason1 = create_fix_reason("Critical bug", 95)
    reason2 = create_fix_reason("Feature", 60)

    report1 = create_fix_report(reason1, 95)
    report2 = create_fix_report(reason2, 60)

    summary = create_fix_summary([report1, report2])

    assert summary.total_items == 2
    assert summary.highest_priority == 95
    assert summary.titles == ["Critical bug", "Feature"]


def test_create_fix_summary_empty():
    summary = create_fix_summary([])

    assert summary.total_items == 0
    assert summary.highest_priority == 0
    assert summary.titles == []

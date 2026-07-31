from ai_asset_platform.developer.fix_reason import create_fix_reason
from ai_asset_platform.developer.fix_report import create_fix_report


def test_create_fix_report():
    reason = create_fix_reason("Critical bug", 95)
    report = create_fix_report(reason, 95)

    assert report.title == "Critical bug"
    assert report.priority == 95
    assert "最優先" in report.reason

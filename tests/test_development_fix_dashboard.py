from ai_asset_platform.developer.fix_dashboard import create_fix_dashboard
from ai_asset_platform.developer.fix_reason import create_fix_reason
from ai_asset_platform.developer.fix_report import create_fix_report


def test_create_fix_dashboard():
    reason = create_fix_reason("Critical bug", 90)
    report = create_fix_report(reason, 90)

    dashboard = create_fix_dashboard([report])

    assert "[Priority 90]" in dashboard
    assert "Critical bug" in dashboard
    assert "Reason:" in dashboard


def test_create_fix_dashboard_empty():
    dashboard = create_fix_dashboard([])

    assert dashboard == "No fixes."


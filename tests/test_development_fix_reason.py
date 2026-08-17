from ai_asset_platform.developer.fix_reason import create_fix_reason


def test_create_fix_reason_high_priority():
    result = create_fix_reason("Critical bug", 95)

    assert result.title == "Critical bug"
    assert "最優先" in result.reason


def test_create_fix_reason_medium_priority():
    result = create_fix_reason("Feature", 60)

    assert result.title == "Feature"
    assert "通常" in result.reason


def test_create_fix_reason_low_priority():
    result = create_fix_reason("Cleanup", 20)

    assert result.title == "Cleanup"
    assert "緊急性は低い" in result.reason

from ai_asset_platform.developer.next_fix import select_next_fix


def test_select_next_fix_returns_highest_priority():
    candidates = [
        {"name": "Fix A", "priority": 50},
        {"name": "Fix B", "priority": 90},
        {"name": "Fix C", "priority": 70},
    ]

    result = select_next_fix(candidates)

    assert result["name"] == "Fix B"
    assert result["priority"] == 90


def test_select_next_fix_returns_none_when_empty():
    assert select_next_fix([]) is None

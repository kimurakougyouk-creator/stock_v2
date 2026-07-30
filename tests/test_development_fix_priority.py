from ai_asset_platform.developer.fix_priority import (
    FixSuggestion,
    prioritize_fixes,
)


def test_prioritize_fixes():
    fixes = [
        FixSuggestion("Update README", "low"),
        FixSuggestion("Fix crash", "critical"),
        FixSuggestion("Improve logging", "medium"),
        FixSuggestion("Handle timeout", "high"),
    ]

    ordered = prioritize_fixes(fixes)

    assert [f.title for f in ordered] == [
        "Fix crash",
        "Handle timeout",
        "Improve logging",
        "Update README",
    ]

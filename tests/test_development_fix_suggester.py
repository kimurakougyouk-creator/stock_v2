from ai_asset_platform.developer.fix_suggester import suggest_fixes


def test_suggest_fixes_generates_expected_titles():
    issues = [
        "Long function detected",
        "Duplicate code found",
        "Missing type hints",
        "Unknown issue",
    ]

    suggestions = suggest_fixes(issues)

    titles = [item.title for item in suggestions]

    assert titles == [
        "関数を分割する",
        "共通化する",
        "型ヒントを追加する",
        "コードレビューを行う",
    ]

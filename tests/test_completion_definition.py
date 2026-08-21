from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_completion_definition_requires_more_than_pytest():
    text = (ROOT / "docs" / "completion_definition.md").read_text(encoding="utf-8")
    assert "Passing pytest alone is necessary but not sufficient" in text
    assert "Live Trading remains disabled/fail-closed" in text
    assert "secret scanning passes in CI" in text
    assert "provider credentials are revoked/removed" in text

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_hardening_scope_forbids_trading_semantic_changes():
    text = (ROOT / "docs" / "change_scope.md").read_text(encoding="utf-8")
    assert "must not change trading strategy thresholds" in text
    assert "portfolio risk limits" in text
    assert "enable Live Trading" in text
    assert "claim new asset classes as implemented" in text

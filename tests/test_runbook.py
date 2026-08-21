from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_runbook_exposes_only_three_normal_operator_commands():
    text = (ROOT / "docs" / "runbook.md").read_text(encoding="utf-8")
    assert "bash scripts/setup.sh" in text
    assert "bash scripts/run.sh" in text
    assert "bash scripts/audit_foundation.sh" in text
    assert "does not transmit an order" in text
    assert "remains disabled/fail-closed" in text

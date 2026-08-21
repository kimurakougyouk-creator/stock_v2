from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_audit_docs_state_no_order_transmission_and_no_live_enablement():
    text = (ROOT / "docs" / "foundation_audit.md").read_text(encoding="utf-8")
    assert "does not transmit an order" in text
    assert "Live Trading is not enabled" in text

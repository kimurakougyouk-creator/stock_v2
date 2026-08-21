from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_ci_contract_forbids_order_transmission_and_live_enablement():
    text = (ROOT / "docs" / "ci_contract.md").read_text(encoding="utf-8")
    assert "never transmit a Paper order from CI" in text
    assert "never enable Live Trading from CI" in text
    assert "without real credentials" in text

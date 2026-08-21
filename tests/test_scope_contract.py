from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_scope_preserves_multi_asset_target_and_requires_evidence():
    text = (ROOT / "docs" / "scope.md").read_text(encoding="utf-8")
    for term in ("Japan stocks", "US and other overseas stocks", "ETFs", "FX", "futures", "options", "crypto assets"):
        assert term in text
    assert "marked supported only after" in text
    assert "Do not weaken the common safety guards" in text

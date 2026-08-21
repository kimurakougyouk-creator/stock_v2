from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_manual_checks_document_identifies_provider_side_revocation():
    text = (ROOT / "docs" / "remaining_manual_checks.md").read_text(encoding="utf-8")
    assert "Google Account" in text
    assert "revoked/removed" in text
    assert "only provider-side credential check" in text

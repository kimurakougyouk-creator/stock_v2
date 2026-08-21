from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_secret_scan_docs_do_not_overclaim_detection():
    text = (ROOT / "docs" / "security_limitations.md").read_text(encoding="utf-8")
    assert "not a guarantee" in text
    assert "does not replace provider-side credential revocation" in text
    assert "must be revoked at the provider" in text

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_issue_audit_keeps_google_revocation_external_and_live_fail_closed():
    text = (ROOT / "docs" / "issue_audit_status.md").read_text(encoding="utf-8")
    assert "Google Account" in text
    assert "Live Trading remains fail-closed" in text
    assert "do not restore the obsolete no-order architecture" in text

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_audit_template_requires_explicit_status_and_external_evidence():
    text = (ROOT / "docs" / "audit_evidence_template.md").read_text(encoding="utf-8")
    assert "complete / partial / blocked / superseded" in text
    assert "external evidence" in text
    assert "Never mark a requirement complete" in text

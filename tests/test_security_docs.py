from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_security_docs_require_revocation_before_history_rewrite():
    text = (ROOT / "docs" / "security.md").read_text(encoding="utf-8")
    revoke_pos = text.index("Revoke/disable the exposed credential")
    history_pos = text.index("Consider Git-history rewriting")
    assert revoke_pos < history_pos
    assert "does not replace revocation" in text

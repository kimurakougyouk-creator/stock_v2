from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_issue23_audit_preserves_current_paper_architecture():
    text = (ROOT / "docs" / "issue23_audit.md").read_text(encoding="utf-8")
    assert "Do not reintroduce the obsolete architecture" in text
    assert "Paper order execution remains a separate explicit opt-in path" in text
    assert "Live Trading remains fail-closed" in text

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_issue8_mapping_requires_ci_before_completion():
    text = (ROOT / "docs" / "issue8_completion.md").read_text(encoding="utf-8")
    assert "thin wrapper" in text
    assert "does not duplicate trading logic" in text
    assert "complete only after CI passes" in text

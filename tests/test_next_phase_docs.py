from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_next_phase_requires_foundation_completion_first():
    text = (ROOT / "docs" / "next_phase.md").read_text(encoding="utf-8")
    assert "only after the foundation completion definition is satisfied" in text
    assert "one capability slice at a time" in text
    assert "shared abstractions over market-specific duplication" in text

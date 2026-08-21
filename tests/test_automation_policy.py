from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_automation_policy_reserves_manual_work_for_external_actions():
    text = (ROOT / "docs" / "automation_policy.md").read_text(encoding="utf-8")
    assert "Automate repository-side work before asking" in text
    assert "provider-side credential revocation" in text
    assert "Do not split one unavoidable operator action" in text

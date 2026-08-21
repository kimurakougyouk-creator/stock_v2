from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_pytest_workflow_runs_secret_scan_before_tests():
    text = (ROOT / ".github" / "workflows" / "pytest.yml").read_text(encoding="utf-8")
    scan = text.index("python scripts/check_secrets.py")
    tests = text.index("pytest -q")
    assert scan < tests
    assert "fetch-depth: 0" in text

from pathlib import Path
import importlib.util

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_secrets.py"
spec = importlib.util.spec_from_file_location("check_secrets", SCRIPT)
check_secrets = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(check_secrets)


def test_secret_patterns_detect_representative_credentials():
    assert check_secrets.PATTERNS["private key"].search("-----BEGIN PRIVATE KEY-----")
    assert check_secrets.PATTERNS["AWS access key"].search("AKIA1234567890ABCDEF")
    assert check_secrets.PATTERNS["GitHub token"].search("ghp_123456789012345678901234567890123456")


def test_placeholder_assignment_is_not_treated_as_real_secret():
    text = 'APP_PASSWORD = "your_app_password"'
    match = check_secrets.ASSIGNMENT.search(text)
    assert match is not None
    value = match.group(2).lower()
    assert any(marker in value for marker in check_secrets.PLACEHOLDER_MARKERS)

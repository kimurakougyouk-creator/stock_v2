from pathlib import Path


SCRIPT = Path("verify_gemini_env_key_windows.ps1")


def _text() -> str:
    assert SCRIPT.exists(), f"missing required file: {SCRIPT}"
    return SCRIPT.read_text(encoding="utf-8")


def test_verify_gemini_env_key_never_prints_the_key_itself():
    script = _text()
    assert "settings.gemini_api_key" in script
    # Only length/boolean checks are printed, never the key value itself.
    for line in script.splitlines():
        if line.strip().startswith("print("):
            assert "gemini_api_key" not in line or "len(" in line or "bool(" in line


def test_verify_gemini_env_key_live_check_is_opt_in_and_read_only():
    script = _text()
    assert "[switch]$LiveCheck" in script
    assert '"--live-check" in sys.argv and settings.gemini_api_key' in script
    assert "client.request(" in script
    assert "placeOrder(" not in script
    assert "Remove-Item -LiteralPath $tempScript" in script


def test_verify_gemini_env_key_does_not_write_or_overwrite_env():
    # This script only reads .env (via load_ai_settings) and must never
    # create, modify, or delete it.
    script = _text()
    assert "$EnvFile" in script
    assert "Set-Content" not in script
    assert "Remove-Item -LiteralPath $EnvFile" not in script
    assert "WriteAllText($EnvFile" not in script
    assert "WriteAllBytes($EnvFile" not in script

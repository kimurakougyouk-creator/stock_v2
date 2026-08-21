from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_env_example_contains_only_placeholders_and_paper_is_off():
    text = (ROOT / ".env.example").read_text(encoding="utf-8")
    assert "APP_PASSWORD=your_gmail_app_password" in text
    assert "OPENAI_API_KEY=your_openai_api_key" in text
    assert "AI_ASSET_ENABLE_IBKR_PAPER=false" in text
    assert "AI_ASSET_ENABLE_LIVE" not in text

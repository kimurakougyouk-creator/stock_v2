from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_env_template_does_not_offer_live_trading_switches():
    text = (ROOT / ".env.example").read_text(encoding="utf-8").upper()
    assert "LIVE_TRADING" not in text
    assert "ENABLE_LIVE" not in text

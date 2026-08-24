from pathlib import Path


def test_fx_discovery_uses_guarded_ibapi_message_loop():
    text = Path(
        "src/ai_asset_platform/brokers/ibkr_fx_discovery.py"
    ).read_text(encoding="utf-8")
    assert "start_guarded_ibapi_loop" in text
    assert "target=probe.run" not in text
    assert "probe.run" in text


def test_fx_discovery_remains_read_only():
    text = Path(
        "src/ai_asset_platform/brokers/ibkr_fx_discovery.py"
    ).read_text(encoding="utf-8")
    assert "placeOrder(" not in text
    assert "cancelOrder(" not in text
    assert "Order()" not in text

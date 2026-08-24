from pathlib import Path


READ_ONLY_PROBE_FILES = (
    "src/ai_asset_platform/brokers/ibkr_etf_audit.py",
    "src/ai_asset_platform/brokers/ibkr_overnight_audit.py",
    "src/ai_asset_platform/brokers/ibkr_future_discovery.py",
    "src/ai_asset_platform/brokers/ibkr_option_discovery.py",
    "src/ai_asset_platform/brokers/ibkr_crypto_discovery.py",
)


def test_readonly_probe_files_use_guarded_ibapi_message_loop():
    for path in READ_ONLY_PROBE_FILES:
        text = Path(path).read_text(encoding="utf-8")
        assert "run_ibapi_message_loop_safely" in text, path
        assert "target=probe.run" not in text, path
        assert 'kwargs={"client": probe, "errors": probe.errors}' in text, path


def test_multiasset_discovery_files_remain_order_free():
    for path in READ_ONLY_PROBE_FILES[2:]:
        text = Path(path).read_text(encoding="utf-8")
        assert "placeOrder(" not in text, path
        assert "cancelOrder(" not in text, path
        assert "Order()" not in text, path


def test_existing_etf_and_overnight_audits_do_not_gain_order_transmission():
    for path in READ_ONLY_PROBE_FILES[:2]:
        text = Path(path).read_text(encoding="utf-8")
        assert "placeOrder(" not in text, path
        assert "cancelOrder(" not in text, path

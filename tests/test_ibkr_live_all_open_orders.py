from __future__ import annotations

from pathlib import Path

import ai_asset_platform.brokers.ibkr_live_all_open_orders as module


def test_missing_confirmation_blocks_before_probe_creation(monkeypatch):
    class ExplodingProbe:
        def __init__(self):
            raise AssertionError("probe must not be created without confirmation")

    monkeypatch.setattr(module, "_AllOpenOrdersProbe", ExplodingProbe)
    result = module.preview_ibkr_live_all_open_orders(confirmation="")

    assert result.attempted is False
    assert result.ready is False
    assert result.order_sent is False
    assert result.cancel_sent is False
    assert result.live_order_sent is False


def test_live_open_order_snapshot_defaults_to_no_broker_mutation():
    result = module.IbkrLiveAllOpenOrdersSnapshot(
        attempted=True,
        connected=True,
        ready=True,
        endpoint_port=4001,
        orders=(),
    )
    assert result.order_sent is False
    assert result.cancel_sent is False
    assert result.live_order_sent is False


def test_module_uses_only_live_endpoint_constants():
    assert module.LIVE_GATEWAY_PORT == 4001
    assert module.LIVE_TWS_PORT == 7496


def test_module_contains_no_order_mutation_or_preview_api():
    source = Path(
        "src/ai_asset_platform/brokers/ibkr_live_all_open_orders.py"
    ).read_text(encoding="utf-8")
    forbidden = (
        ".placeOrder(",
        ".cancelOrder(",
        "whatIf=True",
        "transmit_ibkr",
        "enable_live_trading = True",
    )
    for token in forbidden:
        assert token not in source

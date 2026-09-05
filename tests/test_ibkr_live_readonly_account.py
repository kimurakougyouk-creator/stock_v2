from __future__ import annotations

from pathlib import Path

import ai_asset_platform.brokers.ibkr_live_readonly_account as module


def test_missing_confirmation_blocks_before_any_live_connection(monkeypatch):
    class ExplodingProbe:
        def __init__(self):
            raise AssertionError("probe must not be created without confirmation")

    monkeypatch.setattr(module, "_AccountSnapshotProbe", ExplodingProbe)

    result = module.preview_ibkr_live_readonly_account_snapshot(
        confirmation="",
    )

    assert result.attempted is False
    assert result.connected is False
    assert result.ready is False
    assert result.blocked_reason == "exact Live read-only confirmation is missing"
    assert result.order_sent is False
    assert result.live_order_sent is False


def test_live_default_endpoint_constants_are_separate_from_paper_defaults():
    assert module.LIVE_GATEWAY_PORT == 4001
    assert module.LIVE_TWS_PORT == 7496
    assert module.LIVE_GATEWAY_PORT != 4002
    assert module.LIVE_TWS_PORT != 7497


def test_account_fingerprint_is_deterministic_and_does_not_expose_raw_id():
    raw = "U1234567"
    fingerprint = module._account_fingerprint(raw)
    assert fingerprint == module._account_fingerprint(raw)
    assert len(fingerprint) == 64
    assert raw not in fingerprint


def test_ready_requires_complete_live_readonly_evidence():
    ready = module.IbkrLiveReadOnlyAccountSnapshot(
        attempted=True,
        connected=True,
        endpoint_port=4001,
        account_fingerprint="a" * 64,
        account_ready=True,
        base_currency="JPY",
        net_liquidation=100000.0,
        available_funds=100000.0,
        gross_position_value=0.0,
        total_cash_value=100000.0,
        positions=(),
        blocked_reason=None,
        order_sent=False,
        live_order_sent=False,
    )
    assert ready.ready is True

    incomplete = module.IbkrLiveReadOnlyAccountSnapshot(
        attempted=True,
        connected=True,
        endpoint_port=4001,
        account_fingerprint="a" * 64,
        account_ready=True,
        base_currency="JPY",
        net_liquidation=None,
        available_funds=None,
        gross_position_value=None,
        total_cash_value=None,
        positions=(),
        blocked_reason=None,
        order_sent=False,
        live_order_sent=False,
    )
    assert incomplete.ready is False


def test_module_contains_no_order_or_live_unlock_api():
    source = Path(
        "src/ai_asset_platform/brokers/ibkr_live_readonly_account.py"
    ).read_text(encoding="utf-8")

    forbidden = (
        ".placeOrder(",
        ".cancelOrder(",
        "transmit_ibkr",
        "enable_live_trading = True",
        "allow_live_trading=True",
        "RUN_MODE=LIVE",
    )
    for token in forbidden:
        assert token not in source

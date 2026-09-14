from __future__ import annotations

import json
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


def test_live_probe_captures_managed_account_fingerprint_not_raw_id():
    """Codex P1: the collector must identify the managed-account fingerprint

    from the same connection so completion can bind this snapshot to the
    intended account instead of accepting any zero-order report on the port.
    """
    probe = module._LiveAllOpenOrdersProbe()
    assert probe.accounts_ready.is_set() is False

    probe.managedAccounts("U_TEST_LIVE_ONLY")
    assert probe.accounts_ready.is_set() is True
    assert probe.accounts == ["U_TEST_LIVE_ONLY"]

    fingerprint = module._account_fingerprint(probe.accounts[0])
    assert len(fingerprint) == 64
    assert "U_TEST_LIVE_ONLY" not in fingerprint


def test_snapshot_and_persisted_report_expose_fingerprint_not_raw_id(tmp_path: Path):
    fingerprint = module._account_fingerprint("U_TEST_LIVE_ONLY")
    snapshot = module.IbkrLiveAllOpenOrdersSnapshot(
        attempted=True,
        connected=True,
        ready=True,
        endpoint_port=4001,
        account_fingerprint=fingerprint,
        orders=(),
    )
    report_path = tmp_path / "report.json"
    module.persist_live_all_open_orders(snapshot, report_path=report_path)
    payload = json.loads(report_path.read_text(encoding="utf-8"))

    assert payload["account_fingerprint"] == fingerprint
    assert payload["raw_account_id_persisted"] is False
    assert "U_TEST_LIVE_ONLY" not in json.dumps(payload)


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

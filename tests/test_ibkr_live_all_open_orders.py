from __future__ import annotations

from pathlib import Path
from threading import Event

import ai_asset_platform.brokers.ibkr_live_all_open_orders as module


def test_missing_confirmation_blocks_before_probe_creation(monkeypatch):
    class ExplodingProbe:
        def __init__(self):
            raise AssertionError("probe must not be created without confirmation")

    monkeypatch.setattr(module, "_LiveAllOpenOrdersProbe", ExplodingProbe)
    result = module.preview_ibkr_live_all_open_orders(confirmation="")

    assert result.attempted is False
    assert result.ready is False
    assert result.order_sent is False
    assert result.cancel_sent is False
    assert result.live_order_sent is False


class _FakeLiveAllOpenOrdersProbe:
    def __init__(self, *, accounts: list[str]):
        self.connected_ready = Event()
        self.accounts_ready = Event()
        self.orders_ready = Event()
        self.orders = []
        self.errors: list[str] = []
        self.fatal = False
        self.accounts = accounts
        self._accounts_to_report = accounts
        self.connected = False

    def connect(self, host, port, client_id):
        self.connected = True
        self.connected_ready.set()

    def run(self):
        return None

    def reqManagedAccts(self):
        self.accounts = self._accounts_to_report
        self.accounts_ready.set()

    def reqAllOpenOrders(self):
        self.orders_ready.set()

    def isConnected(self):
        return self.connected

    def disconnect(self):
        self.connected = False


def test_successful_preview_includes_account_fingerprint(monkeypatch):
    monkeypatch.setattr(
        module,
        "_LiveAllOpenOrdersProbe",
        lambda: _FakeLiveAllOpenOrdersProbe(accounts=["U_LIVE_TEST"]),
    )
    result = module.preview_ibkr_live_all_open_orders(
        timeout=0.1, confirmation=module.CONFIRMATION_VALUE
    )

    assert result.ready is True
    assert result.account_fingerprint == module._account_fingerprint("U_LIVE_TEST")


def test_multiple_managed_accounts_blocks_and_omits_fingerprint(monkeypatch):
    monkeypatch.setattr(
        module,
        "_LiveAllOpenOrdersProbe",
        lambda: _FakeLiveAllOpenOrdersProbe(accounts=["U_ONE", "U_TWO"]),
    )
    result = module.preview_ibkr_live_all_open_orders(
        timeout=0.1, confirmation=module.CONFIRMATION_VALUE
    )

    assert result.ready is False
    assert result.account_fingerprint is None


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

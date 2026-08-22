from types import SimpleNamespace

import ai_asset_platform.brokers.ibkr_account_snapshot as module


class _Event:
    def wait(self, timeout):
        return True
    def set(self):
        return None


class FakeProbe:
    instances = []
    def __init__(self):
        self.connected_ready = _Event()
        self.accounts_ready = _Event()
        self.download_ready = _Event()
        self.summary_ready = _Event()
        self.accounts = []
        self.account_ready = True
        self.account_values = {}
        self.summary_values = {}
        self.portfolio = []
        self.errors = []
        self.fatal_error = None
        self.connected = False
        self.calls = []
        FakeProbe.instances.append(self)
    def connect(self, host, port, client_id):
        self.connected = True
        self.port = port
    def run(self):
        return None
    def reqManagedAccts(self):
        self.accounts = ["DU123"]
    def reqAccountUpdates(self, subscribe, account_id):
        self.calls.append(("updates", subscribe, account_id))
        if subscribe:
            self.account_values[("NetLiquidation", "BASE")] = 1_000_000.0
            self.account_values[("TotalCashValue", "BASE")] = 900_000.0
            self.portfolio = [
                module.IbkrBrokerPosition(
                    symbol="SPY", sec_type="STK", currency="USD", exchange="ARCA",
                    quantity=1.0, market_price=760.0, market_value=760.0,
                    average_cost=750.0, unrealized_pnl=10.0, realized_pnl=0.0,
                )
            ]
    def reqAccountSummary(self, req_id, group, tags):
        self.calls.append(("summary", req_id, group, tags))
        self.summary_values[("NetLiquidation", "JPY")] = 1_000_000.0
        self.summary_values[("AvailableFunds", "JPY")] = 800_000.0
        self.summary_values[("GrossPositionValue", "JPY")] = 200_000.0
        self.summary_values[("TotalCashValue", "JPY")] = 900_000.0
    def cancelAccountSummary(self, req_id):
        self.calls.append(("cancel", req_id))
    def isConnected(self):
        return self.connected
    def disconnect(self):
        self.connected = False


def _config(use_gateway):
    return SimpleNamespace(host="127.0.0.1", port=4002 if use_gateway else 7497, client_id=10)


def test_snapshot_is_read_only_and_captures_broker_base_equity_and_positions(monkeypatch):
    FakeProbe.instances.clear()
    monkeypatch.setattr(module, "_AccountSnapshotProbe", FakeProbe)
    monkeypatch.setattr(module, "create_ibkr_paper_config", _config)

    result = module.preview_ibkr_paper_account_snapshot()

    assert result.ready is True
    assert result.endpoint_port == 4002
    assert result.account_id == "DU123"
    assert result.base_currency == "JPY"
    assert result.net_liquidation == 1_000_000.0
    assert result.available_funds == 800_000.0
    assert result.gross_position_value == 200_000.0
    assert result.total_cash_value == 900_000.0
    assert len(result.positions) == 1
    assert result.positions[0].symbol == "SPY"
    assert result.positions[0].unrealized_pnl == 10.0
    assert result.order_sent is False
    assert not any(call[0] == "order" for call in FakeProbe.instances[0].calls)


def test_snapshot_fails_closed_when_base_currency_is_not_proven(monkeypatch):
    class UnknownBase(FakeProbe):
        def reqAccountSummary(self, req_id, group, tags):
            self.summary_values[("NetLiquidation", "BASE")] = 1_000_000.0
    monkeypatch.setattr(module, "_AccountSnapshotProbe", UnknownBase)
    monkeypatch.setattr(module, "create_ibkr_paper_config", _config)
    result = module.preview_ibkr_paper_account_snapshot()
    assert result.connected is True
    assert result.base_currency is None
    assert result.ready is False
    assert result.order_sent is False

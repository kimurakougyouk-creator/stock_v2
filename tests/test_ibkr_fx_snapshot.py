from types import SimpleNamespace

import ai_asset_platform.brokers.ibkr_fx_snapshot as module


class _ReadyEvent:
    def wait(self, timeout):
        return True

    def set(self):
        return None


class FakeProbe:
    instances = []

    def __init__(self):
        self.connected_ready = _ReadyEvent()
        self.snapshot_ready = _ReadyEvent()
        self.bid = None
        self.ask = None
        self.errors = []
        self.fatal_error = None
        self.connected = False
        self.market_data_calls = []
        FakeProbe.instances.append(self)

    def connect(self, host, port, client_id):
        self.connected = True
        self.port = port
        self.client_id = client_id

    def run(self):
        return None

    def reqMktData(self, req_id, contract, generic_ticks, snapshot, regulatory, options):
        self.market_data_calls.append(
            (req_id, contract, generic_ticks, snapshot, regulatory, options)
        )
        self.bid = 149.90
        self.ask = 150.10

    def isConnected(self):
        return self.connected

    def disconnect(self):
        self.connected = False


class FakeAccountProbe:
    instances = []

    def __init__(self, *, currency):
        self.currency = currency
        self.connected_ready = _ReadyEvent()
        self.account_ready = _ReadyEvent()
        self.fx_ready = _ReadyEvent()
        self.account_id = None
        self.rate = None
        self.errors = []
        self.fatal_error = None
        self.connected = False
        self.calls = []
        FakeAccountProbe.instances.append(self)

    def connect(self, host, port, client_id):
        self.connected = True
        self.port = port
        self.client_id = client_id

    def run(self):
        return None

    def reqManagedAccts(self):
        self.calls.append("managed")
        self.account_id = "DU123"

    def reqAccountUpdates(self, subscribe, account_id):
        self.calls.append((subscribe, account_id))
        if subscribe:
            self.rate = 150.25

    def isConnected(self):
        return self.connected

    def disconnect(self):
        self.connected = False


def _config(use_gateway):
    return SimpleNamespace(
        host="127.0.0.1", port=4002 if use_gateway else 7497, client_id=10
    )


def test_midpoint_requires_two_valid_sides():
    assert module._midpoint(149.9, 150.1) == 150.0
    assert module._midpoint(None, 150.1) is None
    assert module._midpoint(150.2, 150.1) is None
    assert module._midpoint(0, 150.1) is None


def test_snapshot_uses_read_only_market_data_and_returns_midpoint(monkeypatch):
    FakeProbe.instances.clear()
    monkeypatch.setattr(module, "_FxSnapshotProbe", FakeProbe)
    monkeypatch.setattr(module, "create_ibkr_paper_config", _config)

    result = module.preview_ibkr_paper_fx_rate(
        base_currency="USD", quote_currency="JPY"
    )

    assert result.connected is True
    assert result.endpoint_port == 4002
    assert result.base_currency == "USD"
    assert result.quote_currency == "JPY"
    assert result.exchange == "IDEALPRO"
    assert result.bid == 149.90
    assert result.ask == 150.10
    assert result.rate == 150.0
    assert result.source == "MARKET_DATA"
    assert result.ready is True
    assert result.order_sent is False

    call = FakeProbe.instances[0].market_data_calls[0]
    assert call[3] is True
    assert call[4] is False
    assert call[1].secType == "CASH"
    assert call[1].exchange == "IDEALPRO"


def test_account_exchange_rate_is_read_only_broker_fallback(monkeypatch):
    FakeAccountProbe.instances.clear()
    monkeypatch.setattr(module, "_AccountFxProbe", FakeAccountProbe)
    monkeypatch.setattr(module, "create_ibkr_paper_config", _config)

    result = module.preview_ibkr_paper_account_fx_rate(
        base_currency="USD", quote_currency="JPY"
    )

    assert result.connected is True
    assert result.endpoint_port == 4002
    assert result.rate == 150.25
    assert result.source == "ACCOUNT_EXCHANGE_RATE"
    assert result.exchange == "ACCOUNT"
    assert result.bid is None
    assert result.ask is None
    assert result.ready is True
    assert result.order_sent is False
    assert FakeAccountProbe.instances[0].calls == [
        "managed",
        (True, "DU123"),
        (False, "DU123"),
    ]


def test_snapshot_without_bid_ask_uses_account_exchange_rate(monkeypatch):
    class OneSidedProbe(FakeProbe):
        def reqMktData(self, *args):
            self.bid = 149.90
            self.ask = None
            self.errors = ["10197: No market data during competing session"]

    FakeAccountProbe.instances.clear()
    monkeypatch.setattr(module, "_FxSnapshotProbe", OneSidedProbe)
    monkeypatch.setattr(module, "_AccountFxProbe", FakeAccountProbe)
    monkeypatch.setattr(module, "create_ibkr_paper_config", _config)

    result = module.preview_ibkr_paper_fx_rate(
        base_currency="USD", quote_currency="JPY"
    )
    assert result.connected is True
    assert result.rate == 150.25
    assert result.ready is True
    assert result.source == "ACCOUNT_EXCHANGE_RATE"
    assert result.order_sent is False
    assert any("10197" in error for error in result.errors)


def test_snapshot_and_account_rate_both_missing_fail_closed(monkeypatch):
    class OneSidedProbe(FakeProbe):
        def reqMktData(self, *args):
            self.bid = 149.90
            self.ask = None

    class MissingAccountProbe(FakeAccountProbe):
        def reqAccountUpdates(self, subscribe, account_id):
            self.calls.append((subscribe, account_id))
            self.rate = None

    monkeypatch.setattr(module, "_FxSnapshotProbe", OneSidedProbe)
    monkeypatch.setattr(module, "_AccountFxProbe", MissingAccountProbe)
    monkeypatch.setattr(module, "create_ibkr_paper_config", _config)

    result = module.preview_ibkr_paper_fx_rate(
        base_currency="USD", quote_currency="JPY"
    )
    assert result.rate is None
    assert result.ready is False
    assert result.order_sent is False

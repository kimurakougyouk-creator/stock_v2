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
        self.market_data_types = []
        FakeProbe.instances.append(self)

    def connect(self, host, port, client_id):
        self.connected = True
        self.port = port
        self.client_id = client_id

    def run(self):
        return None

    def reqMarketDataType(self, market_data_type):
        self.market_data_types.append(market_data_type)

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


def test_live_snapshot_uses_read_only_market_data_and_returns_midpoint(monkeypatch):
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
    assert FakeProbe.instances[0].market_data_types == []


def test_delayed_snapshot_is_second_broker_only_fallback(monkeypatch):
    class DelayedOnlyProbe(FakeProbe):
        def reqMktData(self, *args):
            self.market_data_calls.append(args)
            if self.market_data_types == [3]:
                self.bid = 149.80
                self.ask = 150.20
            else:
                self.bid = None
                self.ask = None
                self.errors = ["10197: competing live session"]

    FakeProbe.instances.clear()
    monkeypatch.setattr(module, "_FxSnapshotProbe", DelayedOnlyProbe)
    monkeypatch.setattr(module, "create_ibkr_paper_config", _config)

    result = module.preview_ibkr_paper_fx_rate(
        base_currency="USD", quote_currency="JPY"
    )

    assert result.ready is True
    assert result.source == "DELAYED_MARKET_DATA"
    assert result.rate == 150.0
    assert any(instance.market_data_types == [3] for instance in FakeProbe.instances)
    assert any("10197" in error for error in result.errors)
    assert result.order_sent is False


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


def test_all_broker_fx_sources_missing_fail_closed(monkeypatch):
    class MissingProbe(FakeProbe):
        def reqMktData(self, *args):
            self.bid = None
            self.ask = None

    class MissingSummary:
        ready = False
        connected = False
        endpoint_port = None
        base_currency = "USD"
        quote_currency = "JPY"
        exchange = "ACCOUNT_SUMMARY"
        bid = None
        ask = None
        rate = None
        source = "ACCOUNT_SUMMARY_EXCHANGE_RATE"
        errors = ("summary unavailable",)

    class MissingLegacy:
        ready = False
        connected = False
        endpoint_port = None
        base_currency = "USD"
        quote_currency = "JPY"
        exchange = "ACCOUNT"
        bid = None
        ask = None
        rate = None
        source = "ACCOUNT_EXCHANGE_RATE"
        errors = ("legacy unavailable",)

    monkeypatch.setattr(module, "_FxSnapshotProbe", MissingProbe)
    monkeypatch.setattr(module, "create_ibkr_paper_config", _config)
    monkeypatch.setattr(module, "preview_ibkr_paper_account_summary_fx_rate", lambda **kwargs: MissingSummary())
    monkeypatch.setattr(module, "preview_ibkr_paper_account_fx_rate", lambda **kwargs: MissingLegacy())

    result = module.preview_ibkr_paper_fx_rate(
        base_currency="USD", quote_currency="JPY"
    )
    assert result.rate is None
    assert result.ready is False
    assert result.order_sent is False
    assert "summary unavailable" in result.errors
    assert "legacy unavailable" in result.errors

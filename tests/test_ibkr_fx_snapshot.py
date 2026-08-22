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


def test_midpoint_requires_two_valid_sides():
    assert module._midpoint(149.9, 150.1) == 150.0
    assert module._midpoint(None, 150.1) is None
    assert module._midpoint(150.2, 150.1) is None
    assert module._midpoint(0, 150.1) is None


def test_snapshot_uses_read_only_market_data_and_returns_midpoint(monkeypatch):
    FakeProbe.instances.clear()
    monkeypatch.setattr(module, "_FxSnapshotProbe", FakeProbe)
    monkeypatch.setattr(
        module,
        "create_ibkr_paper_config",
        lambda use_gateway: SimpleNamespace(
            host="127.0.0.1", port=4002 if use_gateway else 7497, client_id=10
        ),
    )

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
    assert result.ready is True
    assert result.order_sent is False

    call = FakeProbe.instances[0].market_data_calls[0]
    assert call[3] is True
    assert call[4] is False
    assert call[1].secType == "CASH"
    assert call[1].exchange == "IDEALPRO"


def test_snapshot_without_complete_bid_ask_fails_closed(monkeypatch):
    class OneSidedProbe(FakeProbe):
        def reqMktData(self, *args):
            self.bid = 149.90
            self.ask = None

    monkeypatch.setattr(module, "_FxSnapshotProbe", OneSidedProbe)
    monkeypatch.setattr(
        module,
        "create_ibkr_paper_config",
        lambda use_gateway: SimpleNamespace(host="127.0.0.1", port=4002, client_id=10),
    )

    result = module.preview_ibkr_paper_fx_rate(
        base_currency="USD", quote_currency="JPY"
    )
    assert result.connected is True
    assert result.rate is None
    assert result.ready is False
    assert result.order_sent is False

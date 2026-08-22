from types import SimpleNamespace

import ai_asset_platform.brokers.ibkr_fx_historical as module


class _ReadyEvent:
    def wait(self, timeout):
        return True

    def set(self):
        return None


class FakeProbe:
    instances = []

    def __init__(self):
        self.connected_ready = _ReadyEvent()
        self.history_ready = _ReadyEvent()
        self.closes = []
        self.errors = []
        self.fatal_error = None
        self.connected = False
        self.calls = []
        FakeProbe.instances.append(self)

    def connect(self, host, port, client_id):
        self.connected = True
        self.port = port
        self.client_id = client_id

    def run(self):
        return None

    def reqHistoricalData(self, *args):
        self.calls.append(args)
        self.closes = [149.8, 150.1]

    def isConnected(self):
        return self.connected

    def disconnect(self):
        self.connected = False


def _config(use_gateway):
    return SimpleNamespace(host="127.0.0.1", port=4002 if use_gateway else 7497, client_id=10)


def test_historical_fx_returns_latest_positive_midpoint_close(monkeypatch):
    FakeProbe.instances.clear()
    monkeypatch.setattr(module, "_HistoricalFxProbe", FakeProbe)
    monkeypatch.setattr(module, "create_ibkr_paper_config", _config)

    result = module.preview_ibkr_paper_historical_fx_rate(
        base_currency="USD", quote_currency="JPY"
    )

    assert result.connected is True
    assert result.endpoint_port == 4002
    assert result.rate == 150.1
    assert result.source == "HISTORICAL_MIDPOINT"
    assert result.ready is True
    assert result.order_sent is False
    call = FakeProbe.instances[0].calls[0]
    assert call[4] == "5 mins"
    assert call[5] == "MIDPOINT"
    assert call[6] == 0
    assert call[8] is False


def test_historical_fx_without_positive_close_fails_closed(monkeypatch):
    class MissingProbe(FakeProbe):
        def reqHistoricalData(self, *args):
            self.calls.append(args)
            self.closes = []

    monkeypatch.setattr(module, "_HistoricalFxProbe", MissingProbe)
    monkeypatch.setattr(module, "create_ibkr_paper_config", _config)

    result = module.preview_ibkr_paper_historical_fx_rate(
        base_currency="USD", quote_currency="JPY"
    )

    assert result.rate is None
    assert result.ready is False
    assert result.order_sent is False

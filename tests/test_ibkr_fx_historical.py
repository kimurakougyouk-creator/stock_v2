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
        self.bars = []
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
        self.bars = [(1_000_000.0, 149.8), (1_000_300.0, 150.1)]

    def isConnected(self):
        return self.connected

    def disconnect(self):
        self.connected = False


def _config(use_gateway):
    return SimpleNamespace(host="127.0.0.1", port=4002 if use_gateway else 7497, client_id=10)


def test_historical_fx_returns_latest_fresh_midpoint_close(monkeypatch):
    FakeProbe.instances.clear()
    monkeypatch.setattr(module, "_HistoricalFxProbe", FakeProbe)
    monkeypatch.setattr(module, "create_ibkr_paper_config", _config)

    result = module.preview_ibkr_paper_historical_fx_rate(
        base_currency="USD",
        quote_currency="JPY",
        now_fn=lambda: 1_000_600.0,
    )

    assert result.connected is True
    assert result.endpoint_port == 4002
    assert result.rate == 150.1
    assert result.bar_timestamp == 1_000_300.0
    assert result.age_seconds == 300.0
    assert result.source == "HISTORICAL_MIDPOINT"
    assert result.ready is True
    assert result.order_sent is False
    assert FakeProbe.instances[0].client_id == 276
    call = FakeProbe.instances[0].calls[0]
    assert call[4] == "5 mins"
    assert call[5] == "MIDPOINT"
    assert call[6] == 0
    assert call[7] == 2
    assert call[8] is False


def test_historical_fx_stale_bar_fails_closed(monkeypatch):
    monkeypatch.setattr(module, "_HistoricalFxProbe", FakeProbe)
    monkeypatch.setattr(module, "create_ibkr_paper_config", _config)

    result = module.preview_ibkr_paper_historical_fx_rate(
        base_currency="USD",
        quote_currency="JPY",
        max_age_seconds=600,
        now_fn=lambda: 1_002_000.0,
    )

    assert result.rate is None
    assert result.ready is False
    assert any("stale" in error for error in result.errors)
    assert result.order_sent is False


def test_historical_fx_without_timestamped_positive_bar_fails_closed(monkeypatch):
    class MissingProbe(FakeProbe):
        def reqHistoricalData(self, *args):
            self.calls.append(args)
            self.bars = []

    monkeypatch.setattr(module, "_HistoricalFxProbe", MissingProbe)
    monkeypatch.setattr(module, "create_ibkr_paper_config", _config)

    result = module.preview_ibkr_paper_historical_fx_rate(
        base_currency="USD", quote_currency="JPY", now_fn=lambda: 1_000_600.0
    )

    assert result.rate is None
    assert result.ready is False
    assert result.order_sent is False


def test_historical_fx_future_clock_anomaly_fails_closed(monkeypatch):
    monkeypatch.setattr(module, "_HistoricalFxProbe", FakeProbe)
    monkeypatch.setattr(module, "create_ibkr_paper_config", _config)

    result = module.preview_ibkr_paper_historical_fx_rate(
        base_currency="USD",
        quote_currency="JPY",
        now_fn=lambda: 900_000.0,
    )

    assert result.rate is None
    assert result.ready is False
    assert any("future" in error for error in result.errors)


def test_max_age_must_be_positive(monkeypatch):
    monkeypatch.setattr(module, "create_ibkr_paper_config", _config)
    try:
        module.preview_ibkr_paper_historical_fx_rate(
            base_currency="USD", quote_currency="JPY", max_age_seconds=0
        )
    except ValueError as exc:
        assert "max_age_seconds" in str(exc)
    else:
        raise AssertionError("expected ValueError")

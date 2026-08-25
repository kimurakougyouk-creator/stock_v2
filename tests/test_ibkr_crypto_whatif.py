from types import SimpleNamespace
from threading import Event

import ai_asset_platform.brokers.ibkr_crypto_whatif as audit


def _candidate(exchange="PAXOS"):
    return SimpleNamespace(
        symbol="BTC",
        exchange=exchange,
        currency="USD",
        local_symbol="BTC.USD",
        con_id=123,
        min_tick=0.01,
        min_size=0.0001,
        size_increment=0.0001,
        suggested_size_increment=0.0001,
        order_types="LMT,MKT",
    )


def test_crypto_whatif_fails_closed_when_paper_not_enabled(monkeypatch):
    monkeypatch.setattr(
        audit,
        "SETTINGS",
        SimpleNamespace(enable_ibkr_paper=False, enable_live_trading=False, live_trading_unlocked=False),
    )
    result = audit.run_crypto_whatif_audit(timeout=0.01)
    assert result.any_whatif_accepted is False
    assert result.account_order_validation_proven is False
    assert result.paper_trading_proven is False
    assert result.real_order_sent is False
    assert result.live_order_sent is False
    assert all("not explicitly enabled" in row.errors[0] for row in result.venues)


def test_crypto_whatif_fails_closed_when_live_unlock_is_present(monkeypatch):
    monkeypatch.setattr(
        audit,
        "SETTINGS",
        SimpleNamespace(enable_ibkr_paper=True, enable_live_trading=False, live_trading_unlocked=True),
    )
    result = audit.run_crypto_whatif_audit(timeout=0.01)
    assert result.any_whatif_accepted is False
    assert result.real_order_sent is False
    assert result.live_order_sent is False


def test_venue_probe_uses_crypto_market_cash_quantity_whatif(monkeypatch):
    placed = []

    monkeypatch.setattr(
        audit,
        "discover_ibkr_paper_crypto",
        lambda **kwargs: SimpleNamespace(
            connected=True,
            endpoint_port=4002,
            candidates=(_candidate(kwargs["exchange"]),),
            errors=(),
        ),
    )
    monkeypatch.setattr(
        audit,
        "create_ibkr_paper_config",
        lambda use_gateway: SimpleNamespace(host="127.0.0.1", port=4002, client_id=0),
    )

    class FakeProbe:
        def __init__(self):
            self.ready = Event(); self.ready.set()
            self.preview = Event()
            self.order_id = 77
            self.margin_change = 0.0
            self.commission = 0.0
            self.commission_currency = "USD"
            self.warning = None
            self.errors = []
            self.connected = False
        def connect(self, host, port, client_id): self.connected = True
        def isConnected(self): return self.connected  # noqa: N802
        def disconnect(self): self.connected = False
        def placeOrder(self, order_id, contract, order):  # noqa: N802
            placed.append((order_id, contract, order))
            self.preview.set()

    monkeypatch.setattr(audit, "_CryptoWhatIfProbe", FakeProbe)
    monkeypatch.setattr(audit, "Thread", lambda *args, **kwargs: SimpleNamespace(start=lambda: None))

    row = audit._run_venue("PAXOS", timeout=0.01)
    assert row.whatif_accepted is True
    assert row.real_order_sent is False
    assert row.live_order_sent is False
    assert len(placed) == 1
    order_id, contract, order = placed[0]
    assert order_id == 77
    assert contract.secType == "CRYPTO"
    assert contract.exchange == "PAXOS"
    assert order.action == "BUY"
    assert order.orderType == "MKT"
    assert order.cashQty == audit.DIAGNOSTIC_CASH_QTY_USD
    assert order.tif == "IOC"
    assert order.whatIf is True
    assert order.transmit is True


def test_hard_crypto_rejection_is_not_misclassified_as_preview(monkeypatch):
    monkeypatch.setattr(
        audit,
        "discover_ibkr_paper_crypto",
        lambda **kwargs: SimpleNamespace(
            connected=True,
            endpoint_port=4002,
            candidates=(_candidate(kwargs["exchange"]),),
            errors=(),
        ),
    )
    monkeypatch.setattr(
        audit,
        "create_ibkr_paper_config",
        lambda use_gateway: SimpleNamespace(host="127.0.0.1", port=4002, client_id=0),
    )

    class FakeProbe:
        def __init__(self):
            self.ready = Event(); self.ready.set()
            self.preview = Event()
            self.order_id = 88
            self.margin_change = None
            self.commission = None
            self.commission_currency = None
            self.warning = None
            self.errors = []
            self.connected = False
        def connect(self, host, port, client_id): self.connected = True
        def isConnected(self): return self.connected  # noqa: N802
        def disconnect(self): self.connected = False
        def placeOrder(self, order_id, contract, order):  # noqa: N802
            self.errors.append("10287: Cryptocurrency order is not confirmed")
            self.preview.set()

    monkeypatch.setattr(audit, "_CryptoWhatIfProbe", FakeProbe)
    monkeypatch.setattr(audit, "Thread", lambda *args, **kwargs: SimpleNamespace(start=lambda: None))

    row = audit._run_venue("PAXOS", timeout=0.01)
    assert row.preview_received is False
    assert row.whatif_accepted is False
    assert any(error.startswith("10287:") for error in row.errors)

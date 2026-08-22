from types import SimpleNamespace

import ai_asset_platform.brokers.ibkr_future_discovery as module
from ai_asset_platform.brokers.ibkr_future_discovery import (
    _FutureDiscoveryProbe,
    build_future_discovery_contract,
    discover_ibkr_paper_futures,
)


def test_future_discovery_contract_is_fut_and_has_no_chosen_expiry():
    contract = build_future_discovery_contract(
        symbol="MES", exchange="CME", currency="USD"
    )
    assert contract.symbol == "MES"
    assert contract.secType == "FUT"
    assert contract.exchange == "CME"
    assert contract.currency == "USD"
    assert not getattr(contract, "lastTradeDateOrContractMonth", "")


def test_future_discovery_requires_explicit_identity_fields():
    for kwargs in (
        {"symbol": "", "exchange": "CME", "currency": "USD"},
        {"symbol": "MES", "exchange": "", "currency": "USD"},
        {"symbol": "MES", "exchange": "CME", "currency": ""},
    ):
        try:
            build_future_discovery_contract(**kwargs)
        except ValueError:
            pass
        else:
            raise AssertionError("blank futures identity must fail closed")


def test_discovery_reads_broker_fields_and_never_sends_order(monkeypatch):
    seen = {"ports": [], "requests": 0, "orders": 0}

    def fake_connect(self, host, port, client_id):
        seen["ports"].append(port)
        self.connected_ready.set()

    def fake_req(self, req_id, contract):
        seen["requests"] += 1
        resolved_contract = SimpleNamespace(
            symbol="MES",
            localSymbol="MESZ6",
            exchange="CME",
            currency="USD",
            lastTradeDateOrContractMonth="20261218",
            multiplier="5",
            conId=12345,
        )
        details = SimpleNamespace(
            contract=resolved_contract,
            minTick=0.25,
            timeZoneId="US/Central",
            tradingHours="20260822:CLOSED;20260823:1700-20260824:1600",
            liquidHours="20260823:1700-20260824:1600",
        )
        self.details.append(details)
        self.details_ready.set()

    monkeypatch.setattr(_FutureDiscoveryProbe, "connect", fake_connect)
    monkeypatch.setattr(_FutureDiscoveryProbe, "run", lambda self: None)
    monkeypatch.setattr(_FutureDiscoveryProbe, "reqContractDetails", fake_req)
    monkeypatch.setattr(_FutureDiscoveryProbe, "isConnected", lambda self: False)

    result = discover_ibkr_paper_futures(
        symbol="MES", exchange="CME", timeout=0.0
    )
    assert result.connected is True
    assert result.endpoint_port == 4002
    assert result.order_sent is False
    assert seen == {"ports": [4002], "requests": 1, "orders": 0}
    assert len(result.candidates) == 1
    candidate = result.candidates[0]
    assert candidate.symbol == "MES"
    assert candidate.local_symbol == "MESZ6"
    assert candidate.expiry == "20261218"
    assert candidate.multiplier == "5"
    assert candidate.min_tick == 0.25
    assert candidate.con_id == 12345
    assert candidate.time_zone_id == "US/Central"
    assert candidate.trading_hours is not None


def test_endpoint_fallback_happens_only_before_contract_request(monkeypatch):
    seen = {"ports": [], "requests": []}

    def fake_connect(self, host, port, client_id):
        seen["ports"].append(port)
        if port == 4002:
            self.error(-1, 0, 502, "offline")
        else:
            self.connected_ready.set()

    def fake_req(self, req_id, contract):
        seen["requests"].append(contract.symbol)
        resolved_contract = SimpleNamespace(
            symbol="MES",
            localSymbol="MESZ6",
            exchange="CME",
            currency="USD",
            lastTradeDateOrContractMonth="20261218",
            multiplier="5",
            conId=12345,
        )
        self.details.append(
            SimpleNamespace(
                contract=resolved_contract,
                minTick=0.25,
                timeZoneId="US/Central",
                tradingHours="hours",
                liquidHours="liquid",
            )
        )
        self.details_ready.set()

    monkeypatch.setattr(_FutureDiscoveryProbe, "connect", fake_connect)
    monkeypatch.setattr(_FutureDiscoveryProbe, "run", lambda self: None)
    monkeypatch.setattr(_FutureDiscoveryProbe, "reqContractDetails", fake_req)
    monkeypatch.setattr(_FutureDiscoveryProbe, "isConnected", lambda self: False)

    result = discover_ibkr_paper_futures(
        symbol="MES", exchange="CME", timeout=0.0
    )
    assert seen["ports"] == [4002, 7497]
    assert seen["requests"] == ["MES"]
    assert result.endpoint_port == 7497
    assert result.order_sent is False


def test_connected_but_no_contract_details_does_not_fallback_and_remains_unresolved(monkeypatch):
    seen = {"ports": [], "requests": 0}

    def fake_connect(self, host, port, client_id):
        seen["ports"].append(port)
        self.connected_ready.set()

    def fake_req(self, req_id, contract):
        seen["requests"] += 1
        self.details_ready.set()

    monkeypatch.setattr(_FutureDiscoveryProbe, "connect", fake_connect)
    monkeypatch.setattr(_FutureDiscoveryProbe, "run", lambda self: None)
    monkeypatch.setattr(_FutureDiscoveryProbe, "reqContractDetails", fake_req)
    monkeypatch.setattr(_FutureDiscoveryProbe, "isConnected", lambda self: False)

    result = discover_ibkr_paper_futures(
        symbol="MES", exchange="CME", timeout=0.0
    )
    assert seen["ports"] == [4002]
    assert seen["requests"] == 1
    assert result.connected is True
    assert result.resolved is False
    assert result.candidates == ()
    assert result.order_sent is False

from types import SimpleNamespace
from threading import Event

import pytest
from ibapi.contract import Contract, ContractDetails

import ai_asset_platform.brokers.ibkr_global_stock_discovery as discovery


def test_build_global_stock_contract_requires_explicit_fields():
    contract = discovery.build_global_stock_discovery_contract(
        symbol="7203", exchange="tsej", currency="jpy"
    )
    assert contract.symbol == "7203"
    assert contract.secType == "STK"
    assert contract.exchange == "TSEJ"
    assert contract.currency == "JPY"

    with pytest.raises(ValueError, match="symbol"):
        discovery.build_global_stock_discovery_contract(symbol=" ", exchange="TSEJ", currency="JPY")
    with pytest.raises(ValueError, match="exchange"):
        discovery.build_global_stock_discovery_contract(symbol="7203", exchange=" ", currency="JPY")
    with pytest.raises(ValueError, match="currency"):
        discovery.build_global_stock_discovery_contract(symbol="7203", exchange="TSEJ", currency=" ")


def _details():
    details = ContractDetails()
    contract = Contract()
    contract.symbol = "7203"
    contract.localSymbol = "7203"
    contract.exchange = "TSEJ"
    contract.primaryExchange = "TSEJ"
    contract.currency = "JPY"
    contract.conId = 12345
    details.contract = contract
    details.minTick = 0.1
    details.minSize = 100
    details.sizeIncrement = 100
    details.suggestedSizeIncrement = 100
    details.validExchanges = "TSEJ"
    details.orderTypes = "LMT,MKT"
    details.timeZoneId = "Japan"
    details.tradingHours = "20260824:0900-1500"
    details.liquidHours = "20260824:0900-1500"
    return details


def test_candidate_preserves_broker_contract_and_sizing_metadata():
    candidate = discovery._candidate(_details())
    assert candidate.symbol == "7203"
    assert candidate.primary_exchange == "TSEJ"
    assert candidate.currency == "JPY"
    assert candidate.con_id == 12345
    assert candidate.min_tick == 0.1
    assert candidate.min_size == 100
    assert candidate.size_increment == 100
    assert candidate.suggested_size_increment == 100
    assert candidate.order_types == "LMT,MKT"


def test_nonpositive_or_unparseable_sizing_is_not_invented():
    details = _details()
    details.minSize = 0
    details.sizeIncrement = ""
    details.suggestedSizeIncrement = None
    candidate = discovery._candidate(details)
    assert candidate.min_size is None
    assert candidate.size_increment is None
    assert candidate.suggested_size_increment is None


def test_discovery_is_contract_details_only_and_never_sends_order(monkeypatch):
    details = _details()
    probes = []

    class FakeProbe:
        def __init__(self):
            self.connected_ready = Event(); self.connected_ready.set()
            self.details_ready = Event(); self.details = []; self.errors = []
            self.fatal_error = None; self.requested = []; self.connected = False
            probes.append(self)
        def connect(self, host, port, client_id): self.connected = True
        def run(self): return None
        def reqContractDetails(self, req_id, requested_contract):  # noqa: N802
            self.requested.append((req_id, requested_contract)); self.details.append(details); self.details_ready.set()
        def isConnected(self): return self.connected  # noqa: N802
        def disconnect(self): self.connected = False

    monkeypatch.setattr(discovery, "_GlobalStockProbe", FakeProbe)
    monkeypatch.setattr(discovery, "create_ibkr_paper_config", lambda use_gateway: SimpleNamespace(host="127.0.0.1", port=4002 if use_gateway else 7497, client_id=0))
    result = discovery.discover_ibkr_paper_global_stock(symbol="7203", exchange="TSEJ", currency="JPY", timeout=0.01)
    assert result.connected is True
    assert result.endpoint_port == 4002
    assert result.resolved is True
    assert result.order_sent is False
    assert len(result.candidates) == 1
    assert len(probes) == 1
    assert probes[0].requested[0][1].secType == "STK"
    assert not hasattr(probes[0], "placeOrder")

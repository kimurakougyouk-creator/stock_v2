from types import SimpleNamespace
from threading import Event

import pytest
from ibapi.contract import Contract, ContractDetails

import ai_asset_platform.brokers.ibkr_fx_discovery as discovery


def test_build_fx_contract_requires_explicit_pair_and_exchange():
    contract = discovery.build_fx_discovery_contract(base_currency="eur", quote_currency="usd", exchange="idealpro")
    assert contract.symbol == "EUR"
    assert contract.secType == "CASH"
    assert contract.currency == "USD"
    assert contract.exchange == "IDEALPRO"
    with pytest.raises(ValueError, match="base"):
        discovery.build_fx_discovery_contract(base_currency=" ", quote_currency="USD", exchange="IDEALPRO")
    with pytest.raises(ValueError, match="quote"):
        discovery.build_fx_discovery_contract(base_currency="EUR", quote_currency=" ", exchange="IDEALPRO")
    with pytest.raises(ValueError, match="exchange"):
        discovery.build_fx_discovery_contract(base_currency="EUR", quote_currency="USD", exchange=" ")
    with pytest.raises(ValueError, match="must differ"):
        discovery.build_fx_discovery_contract(base_currency="USD", quote_currency="USD", exchange="IDEALPRO")


def _details():
    details = ContractDetails()
    contract = Contract()
    contract.symbol = "EUR"
    contract.currency = "USD"
    contract.exchange = "IDEALPRO"
    contract.localSymbol = "EUR.USD"
    contract.conId = 12087792
    details.contract = contract
    details.minTick = 0.00005
    details.minSize = 1000
    details.sizeIncrement = 1000
    details.suggestedSizeIncrement = 1000
    details.validExchanges = "IDEALPRO"
    details.orderTypes = "LMT,MKT"
    details.timeZoneId = "US/Eastern"
    details.tradingHours = "20260824:1715-1700"
    details.liquidHours = "20260824:1715-1700"
    return details


def test_candidate_preserves_broker_fx_and_sizing_metadata():
    candidate = discovery._candidate(_details())
    assert candidate.base_currency == "EUR"
    assert candidate.quote_currency == "USD"
    assert candidate.exchange == "IDEALPRO"
    assert candidate.local_symbol == "EUR.USD"
    assert candidate.con_id == 12087792
    assert candidate.min_tick == 0.00005
    assert candidate.min_size == 1000
    assert candidate.size_increment == 1000
    assert candidate.suggested_size_increment == 1000


def test_nonpositive_or_unparseable_sizing_is_not_invented():
    details = _details()
    details.minSize = 0
    details.sizeIncrement = ""
    details.suggestedSizeIncrement = None
    candidate = discovery._candidate(details)
    assert candidate.min_size is None
    assert candidate.size_increment is None
    assert candidate.suggested_size_increment is None


def test_discovery_uses_contract_details_only(monkeypatch):
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
    monkeypatch.setattr(discovery, "_FxDiscoveryProbe", FakeProbe)
    monkeypatch.setattr(discovery, "create_ibkr_paper_config", lambda use_gateway: SimpleNamespace(host="127.0.0.1", port=4002 if use_gateway else 7497, client_id=0))
    result = discovery.discover_ibkr_paper_fx(base_currency="EUR", quote_currency="USD", exchange="IDEALPRO", timeout=0.01)
    assert result.connected is True
    assert result.endpoint_port == 4002
    assert result.resolved is True
    assert result.order_sent is False
    assert len(result.candidates) == 1
    assert probes[0].requested[0][1].secType == "CASH"
    assert not hasattr(probes[0], "placeOrder")

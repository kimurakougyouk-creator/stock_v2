from types import SimpleNamespace
from threading import Event

import pytest
from ibapi.contract import Contract, ContractDetails

import ai_asset_platform.brokers.ibkr_option_discovery as discovery


def test_build_option_contract_requires_explicit_definition():
    contract = discovery.build_option_discovery_contract(
        symbol="SPY",
        exchange="SMART",
        currency="USD",
        expiry="20260918",
        strike=700,
        right="c",
        multiplier="100",
    )
    assert contract.symbol == "SPY"
    assert contract.secType == "OPT"
    assert contract.exchange == "SMART"
    assert contract.currency == "USD"
    assert contract.lastTradeDateOrContractMonth == "20260918"
    assert contract.strike == 700.0
    assert contract.right == "C"
    assert contract.multiplier == "100"

    with pytest.raises(ValueError, match="expiry"):
        discovery.build_option_discovery_contract(
            symbol="SPY", exchange="SMART", currency="USD",
            expiry=" ", strike=700, right="C"
        )
    with pytest.raises(ValueError, match="strike"):
        discovery.build_option_discovery_contract(
            symbol="SPY", exchange="SMART", currency="USD",
            expiry="20260918", strike=0, right="C"
        )
    with pytest.raises(ValueError, match="right"):
        discovery.build_option_discovery_contract(
            symbol="SPY", exchange="SMART", currency="USD",
            expiry="20260918", strike=700, right="X"
        )


def test_candidate_preserves_option_metadata():
    details = ContractDetails()
    contract = Contract()
    contract.symbol = "SPY"
    contract.localSymbol = "SPY   260918C00700000"
    contract.tradingClass = "SPY"
    contract.exchange = "SMART"
    contract.currency = "USD"
    contract.lastTradeDateOrContractMonth = "20260918"
    contract.strike = 700
    contract.right = "C"
    contract.multiplier = "100"
    contract.conId = 123
    details.contract = contract
    details.minTick = 0.01
    details.validExchanges = "SMART,CBOE"
    details.orderTypes = "LMT,MKT"

    candidate = discovery._candidate(details)
    assert candidate.symbol == "SPY"
    assert candidate.expiry == "20260918"
    assert candidate.strike == 700.0
    assert candidate.right == "C"
    assert candidate.multiplier == "100"
    assert candidate.con_id == 123
    assert candidate.min_tick == 0.01


def test_option_discovery_never_has_order_path(monkeypatch):
    details = ContractDetails()
    contract = Contract()
    contract.symbol = "SPY"
    contract.exchange = "SMART"
    contract.currency = "USD"
    contract.lastTradeDateOrContractMonth = "20260918"
    contract.strike = 700
    contract.right = "C"
    contract.multiplier = "100"
    contract.conId = 1
    details.contract = contract
    details.minTick = 0.01

    probes = []

    class FakeProbe:
        def __init__(self):
            self.connected_ready = Event(); self.connected_ready.set()
            self.details_ready = Event()
            self.details = []
            self.errors = []
            self.fatal_error = None
            self.connected = False
            self.requested = []
            probes.append(self)
        def connect(self, host, port, client_id): self.connected = True
        def run(self): return None
        def reqContractDetails(self, req_id, requested_contract):  # noqa: N802
            self.requested.append((req_id, requested_contract))
            self.details.append(details)
            self.details_ready.set()
        def isConnected(self): return self.connected  # noqa: N802
        def disconnect(self): self.connected = False

    monkeypatch.setattr(discovery, "_OptionDiscoveryProbe", FakeProbe)
    monkeypatch.setattr(
        discovery,
        "create_ibkr_paper_config",
        lambda use_gateway: SimpleNamespace(
            host="127.0.0.1", port=4002 if use_gateway else 7497, client_id=0
        ),
    )

    result = discovery.discover_ibkr_paper_option(
        symbol="SPY", exchange="SMART", currency="USD",
        expiry="20260918", strike=700, right="C", multiplier="100", timeout=0.01
    )

    assert result.connected is True
    assert result.endpoint_port == 4002
    assert result.resolved is True
    assert result.order_sent is False
    assert probes[0].requested[0][1].secType == "OPT"
    assert not hasattr(probes[0], "placeOrder")

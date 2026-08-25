from types import SimpleNamespace
from threading import Event

import pytest
from ibapi.contract import Contract, ContractDetails

import ai_asset_platform.brokers.ibkr_crypto_discovery as discovery


def test_build_crypto_contract_requires_explicit_fields():
    contract = discovery.build_crypto_discovery_contract(
        symbol="btc", exchange="paxos", currency="usd"
    )
    assert contract.symbol == "BTC"
    assert contract.secType == "CRYPTO"
    assert contract.exchange == "PAXOS"
    assert contract.currency == "USD"

    with pytest.raises(ValueError, match="symbol"):
        discovery.build_crypto_discovery_contract(symbol=" ", exchange="PAXOS", currency="USD")
    with pytest.raises(ValueError, match="exchange"):
        discovery.build_crypto_discovery_contract(symbol="BTC", exchange=" ", currency="USD")
    with pytest.raises(ValueError, match="currency"):
        discovery.build_crypto_discovery_contract(symbol="BTC", exchange="PAXOS", currency=" ")


def test_candidate_preserves_crypto_metadata():
    details = ContractDetails()
    contract = Contract()
    contract.symbol = "BTC"
    contract.exchange = "PAXOS"
    contract.currency = "USD"
    contract.localSymbol = "BTC.USD"
    contract.conId = 123
    details.contract = contract
    details.minTick = 0.01
    details.minSize = 0.0001
    details.sizeIncrement = 0.0001
    details.suggestedSizeIncrement = 0.0001
    details.validExchanges = "PAXOS"
    details.orderTypes = "LMT,MKT"

    candidate = discovery._candidate(details)
    assert candidate.symbol == "BTC"
    assert candidate.exchange == "PAXOS"
    assert candidate.currency == "USD"
    assert candidate.local_symbol == "BTC.USD"
    assert candidate.con_id == 123
    assert candidate.min_tick == 0.01
    assert candidate.min_size == 0.0001
    assert candidate.size_increment == 0.0001
    assert candidate.suggested_size_increment == 0.0001


def test_crypto_discovery_is_read_only(monkeypatch):
    details = ContractDetails()
    contract = Contract()
    contract.symbol = "BTC"
    contract.exchange = "PAXOS"
    contract.currency = "USD"
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

    monkeypatch.setattr(discovery, "_CryptoDiscoveryProbe", FakeProbe)
    monkeypatch.setattr(
        discovery,
        "create_ibkr_paper_config",
        lambda use_gateway: SimpleNamespace(
            host="127.0.0.1", port=4002 if use_gateway else 7497, client_id=0
        ),
    )

    result = discovery.discover_ibkr_paper_crypto(
        symbol="BTC", exchange="PAXOS", currency="USD", timeout=0.01
    )

    assert result.connected is True
    assert result.endpoint_port == 4002
    assert result.resolved is True
    assert result.order_sent is False
    assert probes[0].requested[0][1].secType == "CRYPTO"
    assert not hasattr(probes[0], "placeOrder")

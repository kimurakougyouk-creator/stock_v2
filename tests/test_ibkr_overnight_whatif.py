from types import SimpleNamespace

import pytest

from ai_asset_platform.brokers.ibkr_config import IbkrConnectionConfig
from ai_asset_platform.brokers.ibkr_overnight_whatif import (
    _WhatIfProbe,
    preview_ibkr_paper_overnight_order,
)


def test_whatif_rejects_unverified_quantity():
    with pytest.raises(RuntimeError, match="quantity 1"):
        preview_ibkr_paper_overnight_order(limit_price=768.0, quantity=2)


def test_whatif_rejects_non_positive_price():
    with pytest.raises(ValueError, match="positive"):
        preview_ibkr_paper_overnight_order(limit_price=0.0)


def test_whatif_requires_tws_paper_port():
    with pytest.raises(RuntimeError, match="7497"):
        preview_ibkr_paper_overnight_order(
            limit_price=768.0,
            config=IbkrConnectionConfig(port=4002),
        )


def test_probe_collects_whatif_order_state():
    probe = _WhatIfProbe()
    state = SimpleNamespace()
    order = SimpleNamespace(whatIf=True)
    probe.openOrder(7, SimpleNamespace(), order, state)
    assert probe.order_state is state
    assert probe.preview_ready.is_set()


def test_single_session_resolves_both_contracts_and_requests_preview_once(monkeypatch):
    seen = {"connect": 0, "contracts": [], "places": 0}

    prepared = SimpleNamespace(
        contract=SimpleNamespace(exchange="OVERNIGHT", primaryExchange="ARCA"),
        order=SimpleNamespace(whatIf=False, transmit=False),
    )

    def fake_prepare(spec, *, config, verified_paper_test_quantity):
        seen["verified_qty"] = verified_paper_test_quantity
        seen["limit_price"] = spec.limit_price
        seen["primary"] = spec.primary_exchange
        return prepared

    monkeypatch.setattr(
        "ai_asset_platform.brokers.ibkr_overnight_whatif.prepare_ibkr_overnight_paper_limit_order",
        fake_prepare,
    )

    def fake_connect(self, host, port, client_id):
        seen["connect"] += 1
        seen["client_id"] = client_id
        self.next_order_id = 55
        self.connected_ready.set()

    def fake_req_contract_details(self, req_id, contract):
        seen["contracts"].append((req_id, contract.exchange, getattr(contract, "primaryExchange", "")))
        if req_id == 1:
            resolved = SimpleNamespace(symbol="SPY", primaryExchange="ARCA")
        else:
            resolved = SimpleNamespace(symbol="SPY", primaryExchange="ARCA")
        self.details_by_req[req_id] = [SimpleNamespace(contract=resolved)]
        self.contract_ready.set()

    def fake_place(self, order_id, contract, order):
        seen["places"] += 1
        seen["order_id"] = order_id
        seen["what_if"] = order.whatIf
        seen["transmit"] = order.transmit
        self.order_state = SimpleNamespace(
            maintMarginChange="12.34",
            commission=1.23,
            commissionCurrency="USD",
            warningText="",
        )
        self.preview_ready.set()

    monkeypatch.setattr(_WhatIfProbe, "connect", fake_connect)
    monkeypatch.setattr(_WhatIfProbe, "run", lambda self: None)
    monkeypatch.setattr(_WhatIfProbe, "reqContractDetails", fake_req_contract_details)
    monkeypatch.setattr(_WhatIfProbe, "placeOrder", fake_place)
    monkeypatch.setattr(_WhatIfProbe, "isConnected", lambda self: False)

    result = preview_ibkr_paper_overnight_order(
        limit_price=768.0,
        config=IbkrConnectionConfig(port=7497, paper_trading=True, allow_live_trading=False),
        timeout=0.0,
    )

    assert seen["connect"] == 1
    assert seen["contracts"] == [(1, "SMART", ""), (2, "OVERNIGHT", "ARCA")]
    assert seen["places"] == 1
    assert seen["verified_qty"] == 1
    assert seen["limit_price"] == 768.0
    assert seen["primary"] == "ARCA"
    assert seen["what_if"] is True
    assert seen["transmit"] is True
    assert seen["order_id"] == 55
    assert result.connected is True
    assert result.preview_received is True
    assert result.order_sent is False
    assert result.primary_exchange == "ARCA"
    assert result.destination == "OVERNIGHT"
    assert result.margin_change == "12.34"
    assert result.commission == 1.23
    assert result.commission_currency == "USD"
    assert result.ready is True


def test_contract_resolution_failure_never_requests_whatif(monkeypatch):
    seen = {"places": 0}

    def fake_connect(self, host, port, client_id):
        self.next_order_id = 55
        self.connected_ready.set()

    def fake_req_contract_details(self, req_id, contract):
        self.contract_ready.set()

    def fake_place(self, order_id, contract, order):
        seen["places"] += 1

    monkeypatch.setattr(_WhatIfProbe, "connect", fake_connect)
    monkeypatch.setattr(_WhatIfProbe, "run", lambda self: None)
    monkeypatch.setattr(_WhatIfProbe, "reqContractDetails", fake_req_contract_details)
    monkeypatch.setattr(_WhatIfProbe, "placeOrder", fake_place)
    monkeypatch.setattr(_WhatIfProbe, "isConnected", lambda self: False)

    result = preview_ibkr_paper_overnight_order(
        limit_price=768.0,
        config=IbkrConnectionConfig(port=7497),
        timeout=0.0,
    )
    assert seen["places"] == 0
    assert result.preview_received is False
    assert result.order_sent is False
    assert result.ready is False


def test_whatif_fatal_server_error_fails_closed(monkeypatch):
    prepared = SimpleNamespace(
        contract=SimpleNamespace(exchange="OVERNIGHT", primaryExchange="ARCA"),
        order=SimpleNamespace(whatIf=False, transmit=False),
    )
    monkeypatch.setattr(
        "ai_asset_platform.brokers.ibkr_overnight_whatif.prepare_ibkr_overnight_paper_limit_order",
        lambda *args, **kwargs: prepared,
    )

    def fake_connect(self, host, port, client_id):
        self.next_order_id = 55
        self.connected_ready.set()

    def fake_req_contract_details(self, req_id, contract):
        resolved = SimpleNamespace(symbol="SPY", primaryExchange="ARCA")
        self.details_by_req[req_id] = [SimpleNamespace(contract=resolved)]
        self.contract_ready.set()

    def fake_place(self, order_id, contract, order):
        self.error(order_id, 0, 201, "Order rejected")

    monkeypatch.setattr(_WhatIfProbe, "connect", fake_connect)
    monkeypatch.setattr(_WhatIfProbe, "run", lambda self: None)
    monkeypatch.setattr(_WhatIfProbe, "reqContractDetails", fake_req_contract_details)
    monkeypatch.setattr(_WhatIfProbe, "placeOrder", fake_place)
    monkeypatch.setattr(_WhatIfProbe, "isConnected", lambda self: False)

    result = preview_ibkr_paper_overnight_order(
        limit_price=768.0,
        config=IbkrConnectionConfig(port=7497),
        timeout=0.0,
    )
    assert result.preview_received is False
    assert result.order_sent is False
    assert result.ready is False
    assert any("201" in item for item in result.errors)

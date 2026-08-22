from dataclasses import replace

import pytest

from ai_asset_platform.brokers.ibkr_option_contract import (
    VerifiedOptionContractSpec,
    build_verified_option_contract,
    verified_option_spec_from_candidate,
)
from ai_asset_platform.brokers.ibkr_option_discovery import IbkrOptionCandidate


def _spec() -> VerifiedOptionContractSpec:
    return VerifiedOptionContractSpec(
        symbol="SPY",
        exchange="SMART",
        currency="USD",
        expiry="20261218",
        strike=760.0,
        right="C",
        multiplier="100",
        con_id=123,
        local_symbol="SPY   261218C00760000",
        trading_class="SPY",
    )


def test_build_verified_option_contract_uses_explicit_fields_only():
    contract = build_verified_option_contract(_spec())
    assert contract.secType == "OPT"
    assert contract.symbol == "SPY"
    assert contract.exchange == "SMART"
    assert contract.currency == "USD"
    assert contract.lastTradeDateOrContractMonth == "20261218"
    assert contract.strike == 760.0
    assert contract.right == "C"
    assert contract.multiplier == "100"
    assert contract.conId == 123


@pytest.mark.parametrize(
    "field,value",
    [
        ("symbol", ""),
        ("exchange", ""),
        ("currency", ""),
        ("expiry", ""),
        ("strike", 0.0),
        ("right", "X"),
        ("multiplier", ""),
        ("con_id", 0),
    ],
)
def test_build_verified_option_contract_fails_closed(field, value):
    with pytest.raises(ValueError):
        build_verified_option_contract(replace(_spec(), **{field: value}))


def test_verified_option_spec_from_candidate_requires_broker_fields():
    candidate = IbkrOptionCandidate(
        symbol="SPY",
        local_symbol="SPY   261218C00760000",
        trading_class="SPY",
        exchange="SMART",
        currency="USD",
        expiry="20261218",
        strike=760.0,
        right="C",
        multiplier="100",
        con_id=123,
        min_tick=0.01,
        valid_exchanges="SMART",
        order_types="LMT",
        time_zone_id="US/Eastern",
        trading_hours="",
        liquid_hours="",
    )
    spec = verified_option_spec_from_candidate(candidate)
    assert spec.expiry == "20261218"
    assert spec.strike == 760.0
    assert spec.right == "C"
    assert spec.multiplier == "100"


def test_verified_option_spec_from_candidate_rejects_missing_multiplier():
    candidate = IbkrOptionCandidate(
        symbol="SPY",
        local_symbol=None,
        trading_class=None,
        exchange="SMART",
        currency="USD",
        expiry="20261218",
        strike=760.0,
        right="C",
        multiplier=None,
        con_id=None,
        min_tick=None,
        valid_exchanges=None,
        order_types=None,
        time_zone_id=None,
        trading_hours=None,
        liquid_hours=None,
    )
    with pytest.raises(ValueError):
        verified_option_spec_from_candidate(candidate)

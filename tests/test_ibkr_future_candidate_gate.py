import pytest

from ai_asset_platform.brokers.ibkr_future_candidate_gate import (
    select_verified_future_candidate,
)
from ai_asset_platform.brokers.ibkr_future_discovery import (
    IbkrFutureCandidate,
    IbkrFutureDiscoveryResult,
)


def _candidate(**overrides):
    values = dict(
        symbol="ES",
        local_symbol="ESZ6",
        exchange="CME",
        currency="USD",
        expiry="20261218",
        multiplier="50",
        con_id=123456,
        min_tick=0.25,
        time_zone_id="US/Central",
        trading_hours="20260824:1700-20260825:1600",
        liquid_hours="20260824:0830-20260824:1515",
    )
    values.update(overrides)
    return IbkrFutureCandidate(**values)


def _result(candidates, *, connected=True, order_sent=False):
    return IbkrFutureDiscoveryResult(
        connected=connected,
        endpoint_port=4002 if connected else None,
        symbol="ES",
        exchange="CME",
        currency="USD",
        candidates=tuple(candidates),
        order_sent=order_sent,
        errors=(),
    )


def test_select_by_local_symbol_returns_exact_candidate():
    result = _result([
        _candidate(local_symbol="ESU6", expiry="20260918", con_id=111),
        _candidate(),
    ])
    selected = select_verified_future_candidate(result, local_symbol="esz6")
    assert selected.local_symbol == "ESZ6"
    assert selected.expiry == "20261218"
    assert selected.multiplier == "50"
    assert selected.con_id == 123456
    assert selected.min_tick == 0.25


def test_select_by_expiry_returns_exact_candidate():
    result = _result([
        _candidate(local_symbol="ESU6", expiry="20260918", con_id=111),
        _candidate(),
    ])
    selected = select_verified_future_candidate(result, expiry="20261218")
    assert selected.local_symbol == "ESZ6"


@pytest.mark.parametrize(
    "kwargs",
    [{}, {"local_symbol": "ESZ6", "expiry": "20261218"}],
)
def test_selector_requires_exactly_one_selector(kwargs):
    with pytest.raises(ValueError, match="exactly one"):
        select_verified_future_candidate(_result([_candidate()]), **kwargs)


def test_ambiguous_selection_fails_closed():
    with pytest.raises(ValueError, match="exactly one contract"):
        select_verified_future_candidate(
            _result([
                _candidate(local_symbol="ESZ6", con_id=1),
                _candidate(local_symbol="ESZ6", con_id=2),
            ]),
            local_symbol="ESZ6",
        )


@pytest.mark.parametrize(
    "overrides,match",
    [
        ({"local_symbol": None}, "local_symbol"),
        ({"expiry": None}, "expiry"),
        ({"multiplier": None}, "multiplier"),
        ({"con_id": None}, "con_id"),
        ({"min_tick": None}, "min_tick"),
    ],
)
def test_missing_product_critical_fields_fail_closed(overrides, match):
    with pytest.raises(ValueError, match=match):
        select_verified_future_candidate(
            _result([_candidate(**overrides)]),
            expiry="20261218" if "local_symbol" in overrides else None,
            local_symbol="ESZ6" if "local_symbol" not in overrides else None,
        )


def test_non_read_only_evidence_is_rejected():
    with pytest.raises(ValueError, match="connected/read-only"):
        select_verified_future_candidate(
            _result([_candidate()], order_sent=True),
            local_symbol="ESZ6",
        )

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from ai_asset_platform.core.settings import PlatformSettings
import ai_asset_platform.reports.live_operational_pilot_readiness as module


FINGERPRINT = "a" * 64
NOW = datetime(2026, 9, 6, 6, 0, 0, tzinfo=timezone.utc)


def _stamp(value: datetime = NOW) -> str:
    return value.isoformat(timespec="seconds")


def _live_account(*, quantity: float = 0.0, checked_at: str | None = None) -> dict:
    positions = []
    if quantity != 0:
        positions.append(
            {
                "symbol": "AAPL",
                "sec_type": "STK",
                "currency": "USD",
                "quantity": quantity,
            }
        )
    return {
        "ready": True,
        "checked_at": checked_at or _stamp(),
        "connection_mode": "LIVE_READ_ONLY",
        "account_fingerprint": FINGERPRINT,
        "base_currency": "JPY",
        "positions": positions,
        "order_sent": False,
        "live_order_sent": False,
    }


def _live_open_orders(count: int = 0, *, checked_at: str | None = None) -> dict:
    return {
        "ready": True,
        "checked_at": checked_at or _stamp(),
        "connection_mode": "LIVE_READ_ONLY",
        "open_order_count": count,
        "order_sent": False,
        "cancel_sent": False,
        "live_order_sent": False,
    }


def _paper_monitor(*, checked_at: str | None = None) -> dict:
    return {
        "status": "WARNING",
        "checked_at": checked_at or _stamp(),
        "accounting_safe": True,
        "risk_safe": True,
        "monitor_order_sent": False,
        "live_order_sent": False,
        "broker": {
            "reconciliation_blocker_count": 0,
            "open_order_count": 0,
        },
    }


def _open_session(*, local_timestamp: str | None = None):
    return SimpleNamespace(
        allowed=True,
        session="CORE_OPEN",
        local_timestamp=local_timestamp or _stamp(),
    )


def _evaluate(**overrides):
    params = {
        "ticker": "AAPL",
        "side": "BUY",
        "quantity": 1,
        "estimated_notional_jpy": 40_000,
        "expected_account_fingerprint": FINGERPRINT,
        "live_account_report": _live_account(),
        "live_open_orders_report": _live_open_orders(),
        "paper_monitor_report": _paper_monitor(),
        "market_session": _open_session(),
        "now": NOW,
    }
    params.update(overrides)
    return module.evaluate_live_operational_pilot_readiness(**params)


def test_one_operational_pilot_does_not_require_strategy_profitability_proof():
    result = _evaluate(
        strategy_deployment_report={"ready_for_live_cash": False},
    )

    assert result.operational_pilot_ready is True
    assert result.strategy_deployment_ready is False
    assert result.status == "READY_FOR_ONE_OPERATIONAL_PILOT"
    assert result.live_account_fresh is True
    assert result.live_open_orders_fresh is True
    assert result.paper_monitor_fresh is True
    assert result.market_session_fresh is True
    assert result.order_sent is False
    assert result.live_order_sent is False


def test_absolute_first_pilot_notional_ceiling_blocks_large_order():
    result = _evaluate(estimated_notional_jpy=50_001)

    assert result.operational_pilot_ready is False
    assert any("ceiling" in blocker for blocker in result.blockers)


def test_unexpected_live_open_order_blocks_pilot():
    result = _evaluate(live_open_orders_report=_live_open_orders(1))
    assert result.operational_pilot_ready is False
    assert "unexpected open Live orders exist" in result.blockers


def test_buy_requires_target_live_position_flat():
    result = _evaluate(live_account_report=_live_account(quantity=1))
    assert result.operational_pilot_ready is False
    assert any("target Live position" in blocker for blocker in result.blockers)


def test_fingerprint_mismatch_blocks_wrong_live_account():
    result = _evaluate(expected_account_fingerprint="b" * 64)
    assert result.operational_pilot_ready is False
    assert "Live account fingerprint is not pinned/matched" in result.blockers


def test_market_closed_blocks_pilot_without_broker_action():
    closed = SimpleNamespace(
        allowed=False,
        session="CLOSED_HOLIDAY",
        local_timestamp=_stamp(),
    )
    result = _evaluate(market_session=closed)
    assert result.operational_pilot_ready is False
    assert result.market_session_allowed is False


def test_scope_is_exact_and_spy_one_share_can_still_be_blocked_by_notional():
    result = _evaluate(
        ticker="SPY",
        quantity=2,
    )
    assert result.operational_pilot_ready is False
    assert any("quantity" in blocker for blocker in result.blockers)


def test_global_live_enable_during_preparation_is_a_blocker():
    settings = PlatformSettings(
        run_mode="LIVE",
        enable_live_trading=True,
        enable_paper_trading=False,
    )
    result = _evaluate(settings=settings)
    assert result.operational_pilot_ready is False
    assert any("global Live Trading lock" in blocker for blocker in result.blockers)


def test_stale_live_account_evidence_blocks_pilot():
    stale = _stamp(NOW - timedelta(seconds=121))
    result = _evaluate(live_account_report=_live_account(checked_at=stale))

    assert result.operational_pilot_ready is False
    assert result.live_account_fresh is False
    assert "Live read-only account evidence is missing or stale" in result.blockers


def test_stale_open_orders_and_paper_monitor_evidence_block_pilot():
    stale = _stamp(NOW - timedelta(minutes=10))
    result = _evaluate(
        live_open_orders_report=_live_open_orders(checked_at=stale),
        paper_monitor_report=_paper_monitor(checked_at=stale),
    )

    assert result.operational_pilot_ready is False
    assert result.live_open_orders_fresh is False
    assert result.paper_monitor_fresh is False
    assert "Live open-order evidence is missing or stale" in result.blockers
    assert "Paper safety monitor evidence is missing or stale" in result.blockers


def test_stale_market_session_evidence_blocks_pilot():
    stale = _stamp(NOW - timedelta(seconds=121))
    result = _evaluate(market_session=_open_session(local_timestamp=stale))

    assert result.operational_pilot_ready is False
    assert result.market_session_fresh is False
    assert "market-session evidence is missing or stale" in result.blockers


def test_future_dated_evidence_fails_closed():
    future = _stamp(NOW + timedelta(seconds=1))
    result = _evaluate(live_account_report=_live_account(checked_at=future))

    assert result.operational_pilot_ready is False
    assert result.live_account_fresh is False


def test_naive_readiness_clock_is_rejected():
    try:
        _evaluate(now=datetime(2026, 9, 6, 6, 0, 0))
    except ValueError as exc:
        assert "timezone-aware" in str(exc)
    else:
        raise AssertionError("naive readiness clock must fail closed")


def test_module_is_read_only_and_contains_no_live_order_transport():
    source = Path(
        "src/ai_asset_platform/reports/live_operational_pilot_readiness.py"
    ).read_text(encoding="utf-8")
    forbidden = (
        ".placeOrder(",
        ".cancelOrder(",
        "transmit_ibkr",
        "enable_live_trading = True",
        "whatIf=True",
    )
    for token in forbidden:
        assert token not in source

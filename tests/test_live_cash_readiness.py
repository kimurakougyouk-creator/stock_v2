from __future__ import annotations

from pathlib import Path

from ai_asset_platform.core.settings import PlatformSettings
from ai_asset_platform.reports.live_cash_readiness import (
    evaluate_live_cash_readiness,
)


def _healthy_monitor() -> dict:
    return {
        "status": "WARNING",
        "accounting_safe": True,
        "risk_safe": True,
        "monitor_order_sent": False,
        "live_order_sent": False,
        "broker": {
            "reconciliation_blocker_count": 0,
            "open_order_count": 0,
        },
    }


def _proven_strategy() -> dict:
    return {
        "closed_trade_count": 5,
        "fees_accounted": True,
        "net_profitability_proven": True,
    }


def test_current_profitability_shape_stays_blocked_fail_closed():
    current_strategy = {
        "closed_trade_count": 0,
        "fees_accounted": False,
        "net_profitability_proven": False,
    }

    result = evaluate_live_cash_readiness(
        strategy_report=current_strategy,
        monitor_report=_healthy_monitor(),
    )

    assert result.status == "BLOCKED"
    assert result.ready_for_live_cash is False
    assert "commissions/fees are not durably accounted" in result.blockers
    assert "net strategy profitability is not proven" in result.blockers
    assert any("transport" in blocker for blocker in result.blockers)
    assert result.order_sent is False
    assert result.live_order_sent is False


def test_gate_can_only_pass_when_every_explicit_evidence_is_true():
    result = evaluate_live_cash_readiness(
        strategy_report=_proven_strategy(),
        monitor_report=_healthy_monitor(),
        live_transport_implemented=True,
    )

    assert result.status == "READY"
    assert result.ready_for_live_cash is True
    assert result.blockers == ()


def test_live_unlock_during_preparation_is_itself_a_blocker():
    live_settings = PlatformSettings(
        run_mode="LIVE",
        enable_live_trading=True,
        enable_paper_trading=False,
    )

    result = evaluate_live_cash_readiness(
        strategy_report=_proven_strategy(),
        monitor_report=_healthy_monitor(),
        settings=live_settings,
        live_transport_implemented=True,
    )

    assert result.ready_for_live_cash is False
    assert result.live_safety_lock_intact is False
    assert any("safety lock" in blocker for blocker in result.blockers)


def test_monitor_critical_or_open_order_blocks_readiness():
    monitor = _healthy_monitor()
    monitor["status"] = "CRITICAL"
    monitor["broker"]["open_order_count"] = 1

    result = evaluate_live_cash_readiness(
        strategy_report=_proven_strategy(),
        monitor_report=monitor,
        live_transport_implemented=True,
    )

    assert result.ready_for_live_cash is False
    assert "Paper operations monitor is CRITICAL" in result.blockers
    assert "unexpected open Paper orders exist" in result.blockers


def test_module_contains_no_broker_or_order_transmission_entrypoint():
    source = Path(
        "src/ai_asset_platform/reports/live_cash_readiness.py"
    ).read_text(encoding="utf-8")

    forbidden = (
        "placeOrder(",
        "place_order(",
        "transmit_ibkr",
        "open_ibkr_",
        "EClient(",
        "enable_live_trading = True",
    )
    for token in forbidden:
        assert token not in source

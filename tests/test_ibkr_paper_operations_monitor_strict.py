from pathlib import Path
from types import SimpleNamespace

import ai_asset_platform.brokers.ibkr_paper_operations_monitor_strict as module
from ai_asset_platform.brokers import ibkr_paper_operations_monitor as base


def _result(*, critical=(), warnings=(), account_ready=False):
    return base.PaperOperationsMonitorResult(
        status="CRITICAL" if critical else "WARNING" if warnings else "HEALTHY",
        checked_at="2026-08-27T18:00:00+09:00",
        critical_reasons=tuple(critical),
        warning_reasons=tuple(warnings),
        account_ready=account_ready,
        execution_snapshot_ready=False,
        endpoint_port=None,
        account_currency=None,
        reconciliation_next_action=None,
        reconciliation_blocker_count=0,
        symbols=(),
        open_orders_ready=False,
        open_order_count=0,
        open_orders=(),
        accounting_safe=True,
        accounting={},
        risk_safe=True,
        risk={},
        runtime_report_present=False,
        runtime_status=None,
        runtime_age_hours=None,
        runtime=None,
        notification_status="NOT_EVALUATED",
        order_sent=False,
        live_order_sent=False,
    )


def _position(symbol, quantity, *, sec_type="STK", currency="USD"):
    return SimpleNamespace(
        symbol=symbol,
        quantity=quantity,
        sec_type=sec_type,
        currency=currency,
    )


def test_legacy_local_paper_rows_are_not_ibkr_operational_positions():
    rows = [
        {
            "mode": "PAPER",
            "status": "RECORDED",
            "ticker": "7203.T",
            "side": "BUY",
            "shares": 100,
        },
        {
            "mode": "IBKR_PAPER",
            "status": "FILLED",
            "ticker": "SPY",
            "side": "BUY",
            "shares": 1,
        },
        {
            "mode": "IBKR_PAPER",
            "status": "SUBMITTED",
            "ticker": "AAPL",
            "side": "BUY",
            "shares": 1,
        },
    ]

    filtered = module._ibkr_confirmed_records(rows)

    assert len(filtered) == 1
    assert filtered[0]["ticker"] == "SPY"


def test_unready_account_is_unknown_currency_not_confirmed_mismatch():
    result = _result(
        critical=("broker and configured account currencies do not match",),
        warnings=("broker Paper account snapshot is not ready",),
        account_ready=False,
    )

    finalized = module._finalize_strict_result(
        result,
        account=SimpleNamespace(ready=False, positions=()),
    )

    assert finalized.status == "WARNING"
    assert finalized.critical_reasons == ()
    assert finalized.warning_reasons == result.warning_reasons


def test_complete_broker_snapshot_rejects_positions_outside_verified_scope():
    account = SimpleNamespace(
        ready=True,
        positions=(
            _position("AAPL", 1),
            _position("7203", 100, currency="JPY"),
        ),
    )

    reasons = module._broker_position_critical_reasons(account)

    assert reasons == ("unverified broker position exists: 7203",)


def test_complete_broker_snapshot_rejects_wrong_verified_quantity():
    account = SimpleNamespace(
        ready=True,
        positions=(_position("SPY", 2),),
    )

    reasons = module._broker_position_critical_reasons(account)

    assert any("SPY broker held quantity 2 differs" in item for item in reasons)


def test_same_symbol_option_cannot_masquerade_as_verified_stock():
    account = SimpleNamespace(
        ready=True,
        positions=(_position("SPY", 1, sec_type="OPT", currency="USD"),),
    )

    reasons = module._broker_position_critical_reasons(account)

    assert any("unverified broker contract exists: SPY" in item for item in reasons)
    assert any("sec_type=OPT" in item for item in reasons)


def test_wrong_contract_currency_is_critical():
    account = SimpleNamespace(
        ready=True,
        positions=(_position("AAPL", 1, sec_type="STK", currency="JPY"),),
    )

    reasons = module._broker_position_critical_reasons(account)

    assert any("unverified broker contract exists: AAPL" in item for item in reasons)
    assert any("currency=JPY" in item for item in reasons)


def test_duplicate_verified_contract_rows_are_aggregated_before_quantity_check():
    account = SimpleNamespace(
        ready=True,
        positions=(
            _position("SPY", 0.5),
            _position("SPY", 0.5),
            _position("9432", 40, currency="JPY"),
            _position("9432", 60, currency="JPY"),
        ),
    )

    assert module._broker_position_critical_reasons(account) == ()


def test_duplicate_verified_contract_rows_cannot_hide_overexposure():
    account = SimpleNamespace(
        ready=True,
        positions=(
            _position("SPY", 1),
            _position("SPY", 1),
        ),
    )

    reasons = module._broker_position_critical_reasons(account)

    assert any("SPY broker held quantity 2 differs" in item for item in reasons)


def test_non_finite_broker_quantity_is_critical():
    account = SimpleNamespace(
        ready=True,
        positions=(_position("SPY", float("nan")),),
    )

    reasons = module._broker_position_critical_reasons(account)

    assert reasons == ("broker position quantity is invalid: SPY",)


def test_unready_broker_snapshot_never_guesses_actual_positions():
    account = SimpleNamespace(
        ready=False,
        positions=(_position("7203", 100, currency="JPY"),),
    )

    assert module._broker_position_critical_reasons(account) == ()


def test_strict_adapter_source_contains_no_order_mutation_api():
    source = Path(module.__file__).read_text(encoding="utf-8")
    assert "placeOrder(" not in source
    assert "cancelOrder(" not in source
    assert "reqOpenOrders(" not in source

import builtins
import inspect
import pytest

import sys
from pathlib import Path
from types import SimpleNamespace

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

# TEST_DECISION_REPORT_ISOLATION
@pytest.fixture(autouse=True)
def isolate_signal_runner_decision_report(monkeypatch, tmp_path):
    """テスト中の判断レポートを一時フォルダへ隔離する。"""

    try:
        import signal_runner
        from decision_log_report import generate_decision_log_report
    except ImportError:
        return

    temporary_report = tmp_path / "decision_log_report.csv"

    def generate_temporary_report():
        return generate_decision_log_report(
            report_file=temporary_report,
        )

    monkeypatch.setattr(
        signal_runner,
        "generate_decision_log_report",
        generate_temporary_report,
    )


@pytest.fixture(autouse=True)
def isolate_signal_runner_daily_state(monkeypatch, request):
    """Keep signal-runner unit tests independent of durable daily order state."""

    if request.node.fspath.basename != "test_signal_runner_final_decision.py":
        return

    import signal_runner

    monkeypatch.setattr(signal_runner, "calculate_daily_buy_order_count", lambda: 0)
    monkeypatch.setattr(signal_runner, "calculate_daily_sell_order_count", lambda: 0)
    monkeypatch.setattr(signal_runner, "calculate_daily_realized_pnl", lambda: 0.0)
    monkeypatch.setattr(signal_runner, "calculate_daily_trading_amount", lambda: 0.0)
    monkeypatch.setattr(
        signal_runner,
        "calculate_repurchase_cooldown_remaining_minutes",
        lambda *args, **kwargs: 0,
    )


@pytest.fixture(autouse=True)
def bridge_legacy_signal_runner_order_spies_to_ibkr_runtime(monkeypatch, request):
    """Keep legacy signal-runner risk tests useful after the final IBKR wiring.

    The production module no longer calls the legacy local create_paper_order()
    path. Older risk/exit tests still spy on that name. For only those two test
    modules, route the mocked IBKR runtime back through the old spy so the tests
    continue to verify their original sizing/blocking behavior without touching
    TWS/Gateway or weakening production opt-in/verification gates.
    """

    if request.node.fspath.basename not in {
        "test_signal_runner_final_decision.py",
        "test_signal_runner_time_stop.py",
    }:
        return

    import signal_runner

    real_getattr = builtins.getattr

    def test_compatible_getattr(obj, name, *default):
        if name == "enable_ibkr_paper":
            return bool(real_getattr(obj, "enable_paper_trading", False))
        return real_getattr(obj, name, *default)

    # These legacy unit tests predate the separate IBKR Paper opt-in. For these
    # two modules only, paper_trading=True also enables the mocked IBKR endpoint.
    # Dedicated final-wiring tests separately verify the real double opt-in gate.
    monkeypatch.setattr(
        signal_runner,
        "getattr",
        test_compatible_getattr,
        raising=False,
    )

    monkeypatch.setattr(
        signal_runner,
        "create_paper_order",
        lambda **kwargs: {
            "side": kwargs["signal"],
            "shares": kwargs["shares"],
        },
        raising=False,
    )

    def verified_quantity_from_caller(_ticker):
        frame = inspect.currentframe()
        caller = frame.f_back if frame is not None else None
        try:
            if caller is None:
                return None
            quantity = caller.f_locals.get("order_shares")
            return int(quantity) if quantity is not None else None
        finally:
            del frame
            del caller

    monkeypatch.setattr(
        signal_runner,
        "verified_paper_test_quantity_for_ticker",
        verified_quantity_from_caller,
    )

    def fake_ibkr_execute(*, ticker, signal, shares, order_intent_id):
        frame = inspect.currentframe()
        caller = frame.f_back if frame is not None else None
        try:
            signal_result = (
                caller.f_locals.get("signal_result", {})
                if caller is not None
                else {}
            )
            reference_price = float(signal_result.get("price") or 0.0)
        finally:
            del frame
            del caller

        signal_runner.create_paper_order(
            ticker=ticker,
            signal=signal,
            shares=shares,
            reference_price=reference_price,
        )

        return SimpleNamespace(
            attempted=True,
            reason="test IBKR Paper dispatch",
            broker_result=SimpleNamespace(
                sent=True,
                status="FILLED",
                message="test fill",
            ),
        )

    monkeypatch.setattr(
        signal_runner,
        "execute_approved_signal_via_ibkr_paper",
        fake_ibkr_execute,
    )


@pytest.fixture(autouse=True)
def isolate_position_exists_test_from_holding_age(monkeypatch, request):
    """Do not let durable holding-age state turn this BUY-block test into Time Stop."""

    if request.node.name != "test_buy_is_blocked_when_position_already_exists":
        return

    import signal_runner

    monkeypatch.setattr(
        signal_runner,
        "calculate_position_holding_days",
        lambda ticker: None,
    )


@pytest.fixture(autouse=True)
def isolate_paper_execution_tests_from_wall_clock(monkeypatch, request):
    """Execution unit/e2e tests exercise fill logic, not the real wall-clock calendar."""

    if request.node.fspath.basename not in {
        "test_paper_trading_runner.py",
        "test_confirmed_fill_evidence_shared.py",
        "test_ibkr_fill_to_equity_e2e.py",
    }:
        return

    import paper_trading_runner

    monkeypatch.setattr(
        paper_trading_runner,
        "evaluate_verified_market_session",
        lambda ticker: SimpleNamespace(
            allowed=True,
            reason="test core session open",
            venue="TEST",
            local_timestamp="2026-09-01T10:00:00-04:00",
            session="TEST_OPEN",
        ),
    )

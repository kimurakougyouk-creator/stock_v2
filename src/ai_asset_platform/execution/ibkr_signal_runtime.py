"""Final safe runtime for one already-approved signal -> IBKR Paper fill.

The caller remains responsible for the existing signal_runner safety checks.
This module also enforces the shared pre-send risk gate so migrated execution
cannot bypass emergency-stop/daily-limit/cooldown controls. It contains no Live
Trading path.
"""

from __future__ import annotations

from pathlib import Path

from ai_asset_platform.account import Account
from ai_asset_platform.brokers.ibkr import IbkrBrokerAdapter
from ai_asset_platform.core.settings import SETTINGS
from ai_asset_platform.execution.legacy_fill_sync import record_confirmed_fill
from ai_asset_platform.execution.service import ExecutionService
from ai_asset_platform.execution.shared_risk_gate import build_shared_risk_gate
from ai_asset_platform.execution.signal_order_bridge import (
    SignalExecutionResult,
    execute_signal_via_ibkr_paper,
)


def execute_approved_signal_via_ibkr_paper(
    *,
    ticker: str,
    signal: str,
    shares: int,
    order_intent_id: str,
    order_log_path: Path = Path("results/paper_orders.jsonl"),
) -> SignalExecutionResult:
    """Execute one pre-approved signal and persist only a confirmed Filled result.

    Paper transmission requires both existing settings gates plus the shared
    risk gate. The temporary Account is deliberately not used as accounting
    authority during migration; the durable legacy order log remains the single
    state read by signal_runner.
    """
    if not SETTINGS.enable_paper_trading:
        return SignalExecutionResult(False, "paper trading disabled")
    if not SETTINGS.enable_ibkr_paper:
        return SignalExecutionResult(False, "IBKR Paper disabled")

    broker = IbkrBrokerAdapter(enable_paper_order_transmission=True)
    service = ExecutionService(
        broker=broker,
        account=Account(initial_cash=0.0),
        risk_gate=build_shared_risk_gate(),
    )

    if not broker.connect():
        raise RuntimeError("IBKR Paperへ接続できません")

    try:
        execution = execute_signal_via_ibkr_paper(
            service=service,
            ticker=ticker,
            signal=signal,
            shares=shares,
            order_intent_id=order_intent_id,
            apply_account_fill=False,
        )
        result = execution.broker_result
        if (
            execution.attempted
            and result is not None
            and getattr(result, "sent", False)
            and getattr(result, "reached_terminal", False)
            and getattr(result, "last_known_status", None) == "Filled"
            and float(getattr(result, "filled_quantity", 0.0)) > 0
            and getattr(result, "avg_fill_price", None) is not None
            and float(result.avg_fill_price) > 0
        ):
            record_confirmed_fill(
                ticker=ticker,
                side=signal,
                filled_quantity=float(result.filled_quantity),
                avg_fill_price=float(result.avg_fill_price),
                order_intent_id=order_intent_id,
                order_log_path=order_log_path,
            )
        return execution
    finally:
        broker.disconnect()

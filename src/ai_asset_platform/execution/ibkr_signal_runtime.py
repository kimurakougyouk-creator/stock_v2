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
from ai_asset_platform.brokers.ibkr_config import create_ibkr_paper_config
from ai_asset_platform.core.settings import SETTINGS
from ai_asset_platform.execution.confirmed_fill_evidence import (
    confirmed_fill_from_broker_result,
)
from ai_asset_platform.execution.legacy_fill_sync import record_confirmed_fill
from ai_asset_platform.execution.service import ExecutionService
from ai_asset_platform.execution.shared_risk_gate import build_shared_risk_gate
from ai_asset_platform.execution.signal_order_bridge import (
    SignalExecutionResult,
    execute_signal_via_ibkr_paper,
)


def _connect_first_available_paper_broker() -> IbkrBrokerAdapter:
    """Connect to Gateway Paper 4002 or TWS Paper 7497 before any order exists.

    Endpoint fallback is safe because it occurs before Contract/order submission.
    Once a broker connects, the caller uses that one session for the single
    execution attempt. No order request is ever retried on another endpoint.
    """
    errors: list[str] = []
    for use_gateway in (True, False):
        config = create_ibkr_paper_config(use_gateway=use_gateway)
        broker = IbkrBrokerAdapter(
            config=config,
            enable_paper_order_transmission=True,
        )
        try:
            if broker.connect():
                return broker
            errors.append(f"port={config.port}: connect returned False")
        except Exception as exc:
            errors.append(f"port={config.port}: {exc}")
        finally:
            if not broker.is_connected():
                try:
                    broker.disconnect()
                except Exception:
                    pass

    detail = " | ".join(errors) if errors else "no Paper endpoint was reachable"
    raise RuntimeError(f"IBKR Paperへ接続できません: {detail}")


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
    risk gate. The local Paper endpoint is selected safely between Gateway 4002
    and TWS 7497 before any broker request exists. Live Trading remains disabled.
    """
    if not SETTINGS.enable_paper_trading:
        return SignalExecutionResult(False, "paper trading disabled")
    if not SETTINGS.enable_ibkr_paper:
        return SignalExecutionResult(False, "IBKR Paper disabled")

    broker = _connect_first_available_paper_broker()
    service = ExecutionService(
        broker=broker,
        account=Account(initial_cash=0.0),
        risk_gate=build_shared_risk_gate(),
    )

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
        confirmed = (
            confirmed_fill_from_broker_result(result, shares)
            if execution.attempted
            else None
        )
        if confirmed is not None:
            confirmed_quantity, confirmed_price = confirmed
            record_confirmed_fill(
                ticker=ticker,
                side=signal,
                filled_quantity=confirmed_quantity,
                avg_fill_price=confirmed_price,
                order_intent_id=order_intent_id,
                order_log_path=order_log_path,
            )
        return execution
    finally:
        broker.disconnect()

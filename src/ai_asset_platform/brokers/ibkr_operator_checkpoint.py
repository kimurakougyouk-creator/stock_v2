"""One-command operator checkpoint for the current IBKR Paper milestone.

This module is deliberately non-live.  It performs the Overnight server-side
what-if preview and a disconnected accounting reconstruction from confirmed
FILLED evidence.  It never sends a real Paper or Live order.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

import order_manager
from config import TRADING_CAPITAL
from ai_asset_platform.brokers.ibkr_overnight_whatif import (
    IbkrOvernightWhatIfResult,
    preview_ibkr_paper_overnight_order,
)
from ai_asset_platform.reports.confirmed_accounting import (
    ConfirmedAccountingSummary,
    audit_confirmed_accounting_file,
)


@dataclass(frozen=True)
class IbkrOperatorCheckpointResult:
    whatif: IbkrOvernightWhatIfResult
    accounting: ConfirmedAccountingSummary

    @property
    def ready_for_paper_e2e_review(self) -> bool:
        return self.whatif.ready


def run_ibkr_operator_checkpoint(*, limit_price: float) -> IbkrOperatorCheckpointResult:
    """Run all non-real-order checks that require the operator's local TWS/Gateway."""
    accounting = audit_confirmed_accounting_file(
        order_manager.ORDER_LOG_PATH,
        initial_capital=float(TRADING_CAPITAL),
    )
    whatif = preview_ibkr_paper_overnight_order(limit_price=float(limit_price))
    return IbkrOperatorCheckpointResult(whatif=whatif, accounting=accounting)


def main() -> int:
    raw_price = os.getenv("IBKR_OVERNIGHT_WHATIF_LIMIT_PRICE", "").strip()
    if not raw_price:
        print("IBKR_OVERNIGHT_WHATIF_LIMIT_PRICE is required. No broker request was sent.")
        return 2
    try:
        price = float(raw_price)
    except ValueError:
        print("IBKR_OVERNIGHT_WHATIF_LIMIT_PRICE must be numeric. No broker request was sent.")
        return 2
    if price <= 0:
        print("IBKR_OVERNIGHT_WHATIF_LIMIT_PRICE must be positive. No broker request was sent.")
        return 2

    result = run_ibkr_operator_checkpoint(limit_price=price)
    whatif = result.whatif
    accounting = result.accounting

    print("===== IBKR PAPER OPERATOR CHECKPOINT =====")
    print("WHATIF CONNECTED       :", whatif.connected)
    print("WHATIF PREVIEW RECEIVED:", whatif.preview_received)
    print("SYMBOL                 :", whatif.symbol)
    print("PRIMARY EXCHANGE       :", whatif.primary_exchange)
    print("DESTINATION            :", whatif.destination)
    print("QUANTITY               :", whatif.quantity)
    print("LIMIT PRICE            :", whatif.limit_price)
    print("REAL ORDER SENT        :", whatif.order_sent)
    print("MARGIN CHANGE          :", whatif.margin_change)
    print("COMMISSION             :", whatif.commission)
    print("COMMISSION CURRENCY    :", whatif.commission_currency)
    print("WARNING                :", whatif.warning_text)
    print("ERRORS                 :", list(whatif.errors))
    print("CONFIRMED FILLS        :", accounting.confirmed_fill_count)
    print("EQUITY POINTS          :", accounting.equity_point_count)
    print("ENDING EQUITY          :", accounting.ending_equity)
    print("REALIZED PNL           :", accounting.realized_pnl)
    print("UNREALIZED PNL         :", accounting.unrealized_pnl)
    print("MAX DRAWDOWN           :", accounting.maximum_drawdown)
    print("READY FOR PAPER E2E REVIEW:", result.ready_for_paper_e2e_review)
    print("REAL ORDER SENT        : False")
    return 0 if result.ready_for_paper_e2e_review else 1


if __name__ == "__main__":
    raise SystemExit(main())

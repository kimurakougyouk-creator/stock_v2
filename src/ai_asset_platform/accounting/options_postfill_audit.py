"""Read-only post-fill accounting/recovery audit for the pinned SPY option.

No Order is created and no broker order API is called. The audit recovers the
latest exact BUY-then-SELL one-contract pair for the proven SPY option from two
execution snapshots, verifies the exact broker position is flat, calculates
multiplier-aware realized PnL, and proves restart-style execution identity
recovery from the second snapshot.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
import time

from ai_asset_platform.accounting.derivative_accounting_boundary import (
    VerifiedDerivativeAccountingSpec,
    derivative_paper_e2e_allowed,
)
from ai_asset_platform.accounting.options_roundtrip_accounting import (
    OptionFillEvidence,
    account_closed_option_roundtrip,
    option_recovery_identity,
)
from ai_asset_platform.brokers.ibkr_execution_snapshot import (
    IbkrExecutionEvidence,
    IbkrPaperExecutionSnapshot,
    preview_ibkr_paper_execution_snapshot,
)
from ai_asset_platform.brokers.ibkr_option_paper_roundtrip import (
    CON_ID,
    CURRENCY,
    EXPIRY,
    LOCAL_SYMBOL,
    MULTIPLIER,
    RIGHT,
    STRIKE,
)
from ai_asset_platform.brokers.ibkr_option_position_probe import probe_option_position


@dataclass(frozen=True)
class OptionPostFillAuditResult:
    ready: bool
    reason: str
    matched_execution_count: int
    selected_buy_order_id: int | None
    selected_sell_order_id: int | None
    selected_exec_ids: tuple[str, ...]
    realized_pnl_usd: Decimal | None
    unrealized_pnl_usd: Decimal | None
    ending_equity_delta_usd: Decimal | None
    max_drawdown_usd: Decimal | None
    ending_contracts: int | None
    restart_recovery_verified: bool
    broker_flat_verified: bool
    real_order_sent: bool = False
    live_order_sent: bool = False


def _match(row: IbkrExecutionEvidence) -> bool:
    return (
        row.sec_type == "OPT"
        and (row.local_symbol or "").upper() == LOCAL_SYMBOL.upper()
        and row.con_id == CON_ID
        and (row.expiry or "") == EXPIRY
        and (row.multiplier or "") == MULTIPLIER
        and row.currency == CURRENCY
        and row.quantity > 0
        and bool(row.exec_id)
        and row.order_id > 0
    )


def _aggregate_order(rows: list[IbkrExecutionEvidence]) -> tuple[float, Decimal, tuple[str, ...]]:
    quantity = sum(float(row.quantity) for row in rows)
    if quantity <= 0:
        raise ValueError("execution quantity must be positive")
    notional = sum(Decimal(str(row.price)) * Decimal(str(row.quantity)) for row in rows)
    avg = notional / Decimal(str(quantity))
    exec_ids = tuple(sorted(row.exec_id for row in rows))
    return quantity, avg, exec_ids


def _select_latest_closed_pair(rows: list[IbkrExecutionEvidence]):
    grouped: dict[int, list[IbkrExecutionEvidence]] = {}
    for row in rows:
        grouped.setdefault(int(row.order_id), []).append(row)

    summaries: dict[int, tuple[str, float, Decimal, tuple[str, ...], IbkrExecutionEvidence]] = {}
    for order_id, items in grouped.items():
        sides = {row.side for row in items}
        if len(sides) != 1:
            continue
        qty, avg, exec_ids = _aggregate_order(items)
        exemplar = items[0]
        summaries[order_id] = (next(iter(sides)), qty, avg, exec_ids, exemplar)

    pairs = []
    for buy_id, buy in summaries.items():
        sell_id = buy_id + 1
        sell = summaries.get(sell_id)
        if sell is None:
            continue
        if buy[0] != "BUY" or sell[0] != "SELL":
            continue
        if abs(buy[1] - 1.0) > 1e-9 or abs(sell[1] - 1.0) > 1e-9:
            continue
        pairs.append((buy_id, sell_id, buy, sell))
    if not pairs:
        return None
    return max(pairs, key=lambda item: item[1])


def _fill(exemplar: IbkrExecutionEvidence, *, exec_id: str, side: str, price: Decimal) -> OptionFillEvidence:
    return OptionFillEvidence(
        execution_id=exec_id,
        con_id=int(exemplar.con_id or 0),
        local_symbol=exemplar.local_symbol or "",
        expiry=exemplar.expiry or "",
        strike=str(STRIKE),
        right=RIGHT,
        currency=exemplar.currency,
        side=side,
        contracts=1,
        price=str(price),
        multiplier=exemplar.multiplier or "",
    )


def evaluate_option_postfill_audit(
    first: IbkrPaperExecutionSnapshot,
    second: IbkrPaperExecutionSnapshot,
    *,
    broker_flat: bool,
) -> OptionPostFillAuditResult:
    if not first.ready or not second.ready:
        return OptionPostFillAuditResult(False, "execution snapshot is not ready", 0, None, None, (), None, None, None, None, None, False, broker_flat)

    rows = [row for row in first.executions if _match(row)]
    selected = _select_latest_closed_pair(rows)
    if selected is None:
        return OptionPostFillAuditResult(False, "no exact consecutive BUY1->SELL1 SPY option execution pair was recoverable", len(rows), None, None, (), None, None, None, None, None, False, broker_flat)

    buy_id, sell_id, buy, sell = selected
    buy_exec_ids = buy[3]
    sell_exec_ids = sell[3]
    selected_ids = tuple(sorted(buy_exec_ids + sell_exec_ids))
    # A synthetic stable execution identity represents a possibly split one-contract order.
    buy_fill = _fill(buy[4], exec_id="+".join(buy_exec_ids), side="BUY", price=buy[2])
    sell_fill = _fill(sell[4], exec_id="+".join(sell_exec_ids), side="SELL", price=sell[2])
    accounting = account_closed_option_roundtrip(buy_fill, sell_fill)

    second_rows = [row for row in second.executions if _match(row) and row.exec_id in selected_ids]
    second_ids = tuple(sorted(row.exec_id for row in second_rows))
    restart_ok = second_ids == selected_ids
    if restart_ok:
        first_identity = option_recovery_identity(buy_fill)
        for row in second_rows:
            if option_recovery_identity(_fill(row, exec_id=row.exec_id, side=row.side, price=Decimal(str(row.price)))) != first_identity:
                restart_ok = False
                break

    unrealized = Decimal("0") if broker_flat else None
    equity_delta = accounting.realized_pnl
    drawdown = max(Decimal("0"), -equity_delta)
    if not restart_ok:
        return OptionPostFillAuditResult(False, "second broker snapshot did not recover the same option execution identities", len(rows), buy_id, sell_id, selected_ids, accounting.realized_pnl, unrealized, equity_delta, drawdown, accounting.ending_contracts, False, broker_flat)
    if not broker_flat:
        return OptionPostFillAuditResult(False, "exact SPY option broker position is not flat", len(rows), buy_id, sell_id, selected_ids, accounting.realized_pnl, None, equity_delta, drawdown, accounting.ending_contracts, True, False)

    spec = VerifiedDerivativeAccountingSpec(
        security_type="OPT",
        multiplier=MULTIPLIER,
        expiry_or_settlement=EXPIRY,
        realized_pnl_verified=True,
        unrealized_pnl_verified=True,
        equity_drawdown_verified=True,
        restart_recovery_verified=True,
    )
    derivative_paper_e2e_allowed(spec)
    return OptionPostFillAuditResult(
        True,
        "verified SPY option Paper executions, multiplier accounting, flat state and restart recovery all passed",
        len(rows),
        buy_id,
        sell_id,
        selected_ids,
        accounting.realized_pnl,
        Decimal("0"),
        equity_delta,
        drawdown,
        accounting.ending_contracts,
        True,
        True,
    )


def run_option_postfill_audit(*, wait_seconds: float = 1.0) -> OptionPostFillAuditResult:
    first = preview_ibkr_paper_execution_snapshot()
    position = probe_option_position()
    broker_flat = bool(position.connected and position.quantity is not None and position.flat)
    time.sleep(max(0.0, float(wait_seconds)))
    second = preview_ibkr_paper_execution_snapshot()
    return evaluate_option_postfill_audit(first, second, broker_flat=broker_flat)


def main() -> int:
    result = run_option_postfill_audit()
    print("===== IBKR PAPER SPY OPTION POST-FILL ACCOUNTING AUDIT =====")
    print("READY                    :", result.ready)
    print("REASON                   :", result.reason)
    print("MATCHED EXECUTIONS       :", result.matched_execution_count)
    print("SELECTED BUY ORDER ID    :", result.selected_buy_order_id)
    print("SELECTED SELL ORDER ID   :", result.selected_sell_order_id)
    print("SELECTED EXEC IDS        :", list(result.selected_exec_ids))
    print("REALIZED PNL USD         :", result.realized_pnl_usd)
    print("UNREALIZED PNL USD       :", result.unrealized_pnl_usd)
    print("ENDING EQUITY DELTA USD  :", result.ending_equity_delta_usd)
    print("MAX DRAWDOWN USD         :", result.max_drawdown_usd)
    print("ENDING CONTRACTS         :", result.ending_contracts)
    print("RESTART RECOVERY VERIFIED:", result.restart_recovery_verified)
    print("BROKER FLAT VERIFIED     :", result.broker_flat_verified)
    print("REAL ORDER SENT          :", result.real_order_sent)
    print("LIVE ORDER SENT          :", result.live_order_sent)
    return 0 if result.ready and not result.real_order_sent and not result.live_order_sent else 2


if __name__ == "__main__":
    raise SystemExit(main())

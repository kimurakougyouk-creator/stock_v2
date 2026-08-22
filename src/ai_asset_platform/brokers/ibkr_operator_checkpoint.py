"""One-command, no-real-order checkpoint for the current IBKR Paper milestone.

The checkpoint combines broker Overnight what-if, broker FX evidence, durable-
ledger accounting, broker account/portfolio reconciliation, and the same pure
verified-Paper BUY preflight used by the normal pilot path. It never sends,
changes, or cancels a real Paper or Live order.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

import order_manager
from config import STOP_LOSS_RATE, TRADING_CAPITAL
from ai_asset_platform.brokers.ibkr_account_snapshot import (
    IbkrPaperAccountSnapshot,
    preview_ibkr_paper_account_snapshot,
)
from ai_asset_platform.brokers.ibkr_fx_evidence import resolve_ibkr_paper_fx_evidence
from ai_asset_platform.brokers.ibkr_fx_snapshot import IbkrFxSnapshotResult
from ai_asset_platform.brokers.ibkr_overnight_whatif import (
    IbkrOvernightWhatIfResult,
    preview_ibkr_paper_overnight_order,
)
from ai_asset_platform.core.settings import SETTINGS
from ai_asset_platform.execution.verified_paper_preflight import (
    VerifiedPaperPreflightError,
    VerifiedPaperPreflightResult,
    evaluate_verified_paper_preflight,
)
from ai_asset_platform.reports.multicurrency_confirmed_accounting import (
    MulticurrencyConfirmedAccountingError,
    MulticurrencyConfirmedAccountingSummary,
    audit_multicurrency_confirmed_accounting,
)

preview_ibkr_paper_fx_rate = resolve_ibkr_paper_fx_evidence


@dataclass(frozen=True)
class IbkrOperatorCheckpointResult:
    whatif: IbkrOvernightWhatIfResult
    fx: IbkrFxSnapshotResult | None
    account: IbkrPaperAccountSnapshot | None
    accounting: MulticurrencyConfirmedAccountingSummary | None
    preflight: VerifiedPaperPreflightResult | None
    accounting_error: str | None = None
    preflight_error: str | None = None
    reconciliation_error: str | None = None
    spy_confirmed_held_quantity: int | None = None
    broker_spy_held_quantity: float | None = None
    legacy_evidence_blockers: tuple[str, ...] = ()
    quarantined_legacy_fill_count: int = 0

    @property
    def ready_for_paper_e2e_review(self) -> bool:
        return (
            self.whatif.ready
            and self.fx is not None
            and self.fx.ready
            and self.account is not None
            and self.account.ready
            and self.accounting_error is None
            and self.reconciliation_error is None
            and not self.legacy_evidence_blockers
            and self.preflight_error is None
            and self.preflight is not None
            and self.preflight.allowed
            and (self.spy_confirmed_held_quantity or 0) == 0
            and (self.broker_spy_held_quantity or 0) == 0
        )


def _legacy_evidence_blockers(records: list[dict], *, account_currency: str) -> tuple[str, ...]:
    blockers: list[str] = []
    account = str(account_currency).strip().upper()
    seen: set[str] = set()
    for index, record in enumerate(records, start=1):
        if not isinstance(record, dict):
            continue
        if str(record.get("mode", "")).strip().upper() != "IBKR_PAPER":
            continue
        if str(record.get("status", "")).strip().upper() != "FILLED":
            continue
        intent = str(record.get("order_intent_id", "")).strip() or f"row-{index}"
        ticker = str(record.get("ticker", "")).strip().upper() or "UNKNOWN"
        currency = str(record.get("currency", "")).strip().upper()
        if not currency:
            key = f"{ticker}:{intent}:missing-currency"
            if key not in seen:
                seen.add(key)
                blockers.append(key)
            continue
        if currency == account:
            continue
        raw = record.get("fx_to_account_rate")
        try:
            rate = float(raw)
        except (TypeError, ValueError):
            rate = 0.0
        if rate <= 0:
            key = f"{ticker}:{intent}:missing-historical-fx"
            if key not in seen:
                seen.add(key)
                blockers.append(key)
    return tuple(blockers)


def _record_has_trusted_accounting_evidence(record: dict, *, account_currency: str) -> bool:
    if not isinstance(record, dict):
        return False
    if str(record.get("status", "")).strip().upper() != "FILLED":
        return False
    mode = str(record.get("mode", "")).strip().upper()
    if mode != "IBKR_PAPER":
        return True
    currency = str(record.get("currency", "")).strip().upper()
    if len(currency) != 3 or not currency.isalpha():
        return False
    account = str(account_currency).strip().upper()
    if currency == account:
        return True
    try:
        rate = float(record.get("fx_to_account_rate"))
    except (TypeError, ValueError):
        return False
    return rate > 0


def _trusted_accounting_records(records: list[dict], *, account_currency: str) -> list[dict]:
    return [record for record in records if _record_has_trusted_accounting_evidence(record, account_currency=account_currency)]


def _confirmed_held_quantity(records: list[dict], *, ticker: str) -> int | None:
    target = str(ticker).strip().upper()
    held = 0
    seen_intents: set[str] = set()
    for record in records:
        if not isinstance(record, dict):
            continue
        if str(record.get("status", "")).strip().upper() != "FILLED":
            continue
        if str(record.get("ticker", "")).strip().upper() != target:
            continue
        intent = str(record.get("order_intent_id", "")).strip()
        if intent and intent in seen_intents:
            continue
        side = str(record.get("side", "")).strip().upper()
        try:
            shares = int(record.get("shares"))
        except (TypeError, ValueError):
            return None
        if shares <= 0 or side not in {"BUY", "SELL"}:
            return None
        if side == "BUY":
            held += shares
        else:
            if shares > held:
                return None
            held -= shares
        if intent:
            seen_intents.add(intent)
    return held


def _broker_symbol_quantity(account: IbkrPaperAccountSnapshot, symbol: str) -> float:
    target = str(symbol).strip().upper()
    return sum(
        float(position.quantity)
        for position in account.positions
        if str(position.symbol).strip().upper() == target
    )


def _reconciliation_error(
    account: IbkrPaperAccountSnapshot,
    *,
    account_currency: str,
    local_spy_held: int | None,
) -> str | None:
    if not account.ready:
        return "broker Paper account snapshot is incomplete or not ready"
    if str(account.base_currency).strip().upper() != str(account_currency).strip().upper():
        return (
            f"configured account currency {account_currency} does not match "
            f"broker base currency {account.base_currency}"
        )
    if account.available_funds is None or account.available_funds < 0:
        return "broker AvailableFunds is unavailable"
    if account.gross_position_value is None or account.gross_position_value < 0:
        return "broker GrossPositionValue is unavailable"
    broker_spy_held = _broker_symbol_quantity(account, "SPY")
    if local_spy_held is None:
        return "local SPY confirmed position cannot be reconstructed safely"
    if abs(float(local_spy_held) - float(broker_spy_held)) > 1e-9:
        return (
            "local/broker SPY position mismatch: "
            f"local={local_spy_held}, broker={broker_spy_held:g}"
        )
    return None


def run_ibkr_operator_checkpoint(*, limit_price: float) -> IbkrOperatorCheckpointResult:
    account_currency = str(SETTINGS.account_currency).strip().upper()
    records = order_manager.load_accounting_orders()
    blockers = _legacy_evidence_blockers(records, account_currency=account_currency)
    trusted_records = _trusted_accounting_records(records, account_currency=account_currency)
    quarantined_count = len(records) - len(trusted_records)
    spy_held = _confirmed_held_quantity(records, ticker="SPY")

    accounting = None
    accounting_error = None
    try:
        accounting = audit_multicurrency_confirmed_accounting(
            trusted_records,
            initial_capital=float(TRADING_CAPITAL),
            account_currency=account_currency,
        )
    except MulticurrencyConfirmedAccountingError as exc:
        accounting_error = str(exc)

    whatif = preview_ibkr_paper_overnight_order(limit_price=float(limit_price))
    account = preview_ibkr_paper_account_snapshot()
    broker_spy_held = _broker_symbol_quantity(account, "SPY") if account.connected else None
    reconcile_error = _reconciliation_error(
        account,
        account_currency=account_currency,
        local_spy_held=spy_held,
    )

    if account_currency == "USD":
        fx = IbkrFxSnapshotResult(
            connected=True, endpoint_port=None, base_currency="USD", quote_currency="USD",
            exchange="IDENTITY", bid=1.0, ask=1.0, rate=1.0, source="IDENTITY",
            order_sent=False, errors=(),
        )
    else:
        fx = preview_ibkr_paper_fx_rate(base_currency="USD", quote_currency=account_currency)

    preflight = None
    preflight_error = None
    if reconcile_error is not None:
        preflight_error = "broker/local position reconciliation is unsafe; BUY preflight remains blocked"
    elif spy_held is None:
        preflight_error = "SPY confirmed position quantity cannot be reconstructed safely"
    elif spy_held > 0:
        preflight_error = f"SPY already has {spy_held} confirmed share(s); duplicate BUY is blocked"
    elif broker_spy_held is not None and broker_spy_held != 0:
        preflight_error = f"broker Paper account already holds {broker_spy_held:g} SPY share(s); duplicate BUY is blocked"
    elif blockers:
        # Quarantine is useful for diagnostics/accounting continuity, but it is
        # not permission to ignore unknown historical exposure before new BUY.
        preflight_error = "legacy confirmed-fill evidence is incomplete; new BUY remains blocked"
    elif accounting_error is not None:
        preflight_error = "accounting is unsafe; BUY preflight remains blocked"
    elif not fx.ready or fx.rate is None:
        preflight_error = "USD account-currency FX evidence is unavailable"
    else:
        try:
            preflight = evaluate_verified_paper_preflight(
                records=trusted_records,
                ticker="SPY",
                side="BUY",
                quantity=1,
                reference_price=float(limit_price),
                instrument_currency="USD",
                settings=SETTINGS,
                initial_capital=float(TRADING_CAPITAL),
                fx_to_account_rate=float(fx.rate),
                stop_loss_rate=float(STOP_LOSS_RATE),
            )
            if not preflight.allowed:
                preflight_error = preflight.reason
        except VerifiedPaperPreflightError as exc:
            preflight_error = str(exc)

    return IbkrOperatorCheckpointResult(
        whatif=whatif,
        fx=fx,
        account=account,
        accounting=accounting,
        preflight=preflight,
        accounting_error=accounting_error,
        preflight_error=preflight_error,
        reconciliation_error=reconcile_error,
        spy_confirmed_held_quantity=spy_held,
        broker_spy_held_quantity=broker_spy_held,
        legacy_evidence_blockers=blockers,
        quarantined_legacy_fill_count=quarantined_count,
    )


def main() -> int:
    raw_price = os.getenv("IBKR_OVERNIGHT_WHATIF_LIMIT_PRICE", "").strip()
    if not raw_price:
        print("IBKR_OVERNIGHT_WHATIF_LIMIT_PRICE is required. No real order was sent.")
        return 2
    try:
        price = float(raw_price)
    except ValueError:
        print("IBKR_OVERNIGHT_WHATIF_LIMIT_PRICE must be numeric. No real order was sent.")
        return 2
    if price <= 0:
        print("IBKR_OVERNIGHT_WHATIF_LIMIT_PRICE must be positive. No real order was sent.")
        return 2

    result = run_ibkr_operator_checkpoint(limit_price=price)
    whatif, fx, account, accounting, preflight = result.whatif, result.fx, result.account, result.accounting, result.preflight

    print("===== IBKR PAPER OPERATOR CHECKPOINT =====")
    print("WHATIF CONNECTED       :", whatif.connected)
    print("WHATIF PREVIEW RECEIVED:", whatif.preview_received)
    print("SYMBOL                 :", whatif.symbol)
    print("PRIMARY EXCHANGE       :", whatif.primary_exchange)
    print("DESTINATION            :", whatif.destination)
    print("QUANTITY               :", whatif.quantity)
    print("LIMIT PRICE            :", whatif.limit_price)
    print("REAL ORDER SENT        :", whatif.order_sent)
    print("WARNING                :", whatif.warning_text)
    print("WHATIF ERRORS          :", list(whatif.errors))
    print("BROKER ACCOUNT READY   :", bool(account and account.ready))
    print("BROKER BASE CURRENCY   :", account.base_currency if account else None)
    print("BROKER NET LIQUIDATION :", account.net_liquidation if account else None)
    print("BROKER AVAILABLE FUNDS :", account.available_funds if account else None)
    print("BROKER GROSS POSITION  :", account.gross_position_value if account else None)
    print("BROKER POSITION COUNT  :", len(account.positions) if account else 0)
    print("BROKER SPY HELD QTY    :", result.broker_spy_held_quantity)
    print("BROKER RECONCILIATION  :", result.reconciliation_error)
    print("BROKER ORDER SENT      :", account.order_sent if account else False)
    print("BROKER ACCOUNT ERRORS  :", list(account.errors) if account else [])
    print("FX READY               :", bool(fx and fx.ready))
    print("FX PAIR                :", f"USD/{SETTINGS.account_currency}")
    print("FX SOURCE              :", fx.source if fx else None)
    print("FX RATE                :", fx.rate if fx else None)
    print("FX ORDER SENT          :", fx.order_sent if fx else False)
    print("FX ERRORS              :", list(fx.errors) if fx else [])
    print("LEGACY EVIDENCE BLOCKERS:", list(result.legacy_evidence_blockers))
    print("QUARANTINED LEGACY FILLS:", result.quarantined_legacy_fill_count)
    print("SPY CONFIRMED HELD QTY :", result.spy_confirmed_held_quantity)
    print("ACCOUNTING SAFE        :", result.accounting_error is None)
    print("ACCOUNTING ERROR       :", result.accounting_error)
    if accounting is not None:
        print("ACCOUNT CURRENCY       :", accounting.account_currency)
        print("CONFIRMED FILLS        :", accounting.confirmed_fill_count)
        print("EQUITY POINTS          :", accounting.equity_point_count)
        print("ENDING EQUITY          :", accounting.ending_equity)
        print("REALIZED PNL           :", accounting.realized_pnl)
        print("UNREALIZED PNL         :", accounting.unrealized_pnl)
        print("MAX DRAWDOWN           :", accounting.maximum_drawdown)
    else:
        print("ACCOUNT CURRENCY       :", SETTINGS.account_currency)
        print("CONFIRMED FILLS        : UNAVAILABLE")
        print("EQUITY POINTS          : UNAVAILABLE")
        print("ENDING EQUITY          : UNAVAILABLE")
        print("REALIZED PNL           : UNAVAILABLE")
        print("UNREALIZED PNL         : UNAVAILABLE")
        print("MAX DRAWDOWN           : UNAVAILABLE")
    print("PREFLIGHT ALLOWED      :", preflight.allowed if preflight else False)
    print("PREFLIGHT ERROR        :", result.preflight_error)
    if preflight is not None:
        print("PLANNED NOTIONAL       :", preflight.planned_notional_account)
        print("HELD QUANTITY          :", preflight.held_quantity)
        print("POSITION COUNT         :", preflight.current_position_count)
        print("DAILY TRADING AMOUNT   :", preflight.daily_trading_amount_account)
    print("READY FOR PAPER E2E REVIEW:", result.ready_for_paper_e2e_review)
    print("REAL ORDER SENT        : False")
    return 0 if result.ready_for_paper_e2e_review else 1


if __name__ == "__main__":
    raise SystemExit(main())

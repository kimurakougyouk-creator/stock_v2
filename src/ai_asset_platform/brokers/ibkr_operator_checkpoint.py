"""One-command, no-real-order checkpoint for the current IBKR Paper milestone.

The checkpoint combines the broker Overnight what-if, broker-provided
USD/account-currency FX evidence, explicit-FX durable-ledger accounting, and the
same pure verified-Paper BUY preflight used by the normal pilot path. It also
reconstructs confirmed position quantity without needing FX so an old
cross-currency fill can still block an accidental duplicate BUY. It never
sends, changes, or cancels a real Paper or Live order.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

import order_manager
from config import STOP_LOSS_RATE, TRADING_CAPITAL
from ai_asset_platform.brokers.ibkr_fx_snapshot import (
    IbkrFxSnapshotResult,
    preview_ibkr_paper_fx_rate,
)
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


@dataclass(frozen=True)
class IbkrOperatorCheckpointResult:
    whatif: IbkrOvernightWhatIfResult
    fx: IbkrFxSnapshotResult | None
    accounting: MulticurrencyConfirmedAccountingSummary | None
    preflight: VerifiedPaperPreflightResult | None
    accounting_error: str | None = None
    preflight_error: str | None = None
    spy_confirmed_held_quantity: int | None = None
    legacy_evidence_blockers: tuple[str, ...] = ()
    quarantined_legacy_fill_count: int = 0

    @property
    def ready_for_paper_e2e_review(self) -> bool:
        return (
            self.whatif.ready
            and self.fx is not None
            and self.fx.ready
            and self.accounting_error is None
            and self.preflight_error is None
            and self.preflight is not None
            and self.preflight.allowed
            and (self.spy_confirmed_held_quantity or 0) == 0
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
    return [
        record
        for record in records
        if _record_has_trusted_accounting_evidence(
            record,
            account_currency=account_currency,
        )
    ]


def _confirmed_held_quantity(records: list[dict], *, ticker: str) -> int | None:
    """Reconstruct quantity from confirmed evidence only, independent of FX valuation."""
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


def run_ibkr_operator_checkpoint(*, limit_price: float) -> IbkrOperatorCheckpointResult:
    """Run all safe checks needed before considering one Overnight Paper E2E."""
    account_currency = str(SETTINGS.account_currency).strip().upper()
    records = order_manager.load_accounting_orders()
    blockers = _legacy_evidence_blockers(records, account_currency=account_currency)
    trusted_records = _trusted_accounting_records(
        records,
        account_currency=account_currency,
    )
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
    if account_currency == "USD":
        fx = IbkrFxSnapshotResult(
            connected=True,
            endpoint_port=None,
            base_currency="USD",
            quote_currency="USD",
            exchange="IDENTITY",
            bid=1.0,
            ask=1.0,
            rate=1.0,
            source="IDENTITY",
            order_sent=False,
            errors=(),
        )
    else:
        fx = preview_ibkr_paper_fx_rate(
            base_currency="USD",
            quote_currency=account_currency,
        )

    preflight = None
    preflight_error = None
    if spy_held is None:
        preflight_error = "SPY confirmed position quantity cannot be reconstructed safely"
    elif spy_held > 0:
        preflight_error = f"SPY already has {spy_held} confirmed share(s); duplicate BUY is blocked"
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
        accounting=accounting,
        preflight=preflight,
        accounting_error=accounting_error,
        preflight_error=preflight_error,
        spy_confirmed_held_quantity=spy_held,
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
    whatif = result.whatif
    fx = result.fx
    accounting = result.accounting
    preflight = result.preflight

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
    print("WHATIF ERRORS          :", list(whatif.errors))
    print("FX READY               :", bool(fx and fx.ready))
    print("FX PAIR                :", f"USD/{SETTINGS.account_currency}")
    print("FX SOURCE              :", fx.source if fx else None)
    print("FX BID                 :", fx.bid if fx else None)
    print("FX ASK                 :", fx.ask if fx else None)
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

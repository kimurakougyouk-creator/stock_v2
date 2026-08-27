"""Read-only IBKR Paper account/portfolio reconciliation snapshot.

Uses documented account-update and account-summary callbacks only. It never
creates, changes, cancels, or transmits an order. The snapshot captures the
broker's current positions plus base-currency NetLiquidation/AvailableFunds/
GrossPositionValue so local durable-ledger state can be checked against the
actual Paper account before any new exposure is considered.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from threading import Event, Thread

from ibapi.client import EClient
from ibapi.contract import Contract
from ibapi.wrapper import EWrapper

from ai_asset_platform.brokers.ibkr_config import create_ibkr_paper_config
from ai_asset_platform.brokers.ibkr_thread_runner import run_ibapi_message_loop_safely


@dataclass(frozen=True)
class IbkrBrokerPosition:
    symbol: str
    sec_type: str
    currency: str
    exchange: str
    quantity: float
    market_price: float
    market_value: float
    average_cost: float
    unrealized_pnl: float
    realized_pnl: float


@dataclass(frozen=True)
class IbkrPaperAccountSnapshot:
    connected: bool
    endpoint_port: int | None
    account_id: str | None
    account_ready: bool
    base_currency: str | None
    net_liquidation: float | None
    available_funds: float | None
    gross_position_value: float | None
    total_cash_value: float | None
    positions: tuple[IbkrBrokerPosition, ...] = ()
    order_sent: bool = False
    errors: tuple[str, ...] = field(default_factory=tuple)

    @property
    def ready(self) -> bool:
        return (
            self.connected
            and self.account_ready
            and self.account_id is not None
            and self.base_currency is not None
            and self.net_liquidation is not None
            and self.net_liquidation > 0
            and not self.order_sent
        )


def _parse_error(args: tuple[object, ...]) -> tuple[int, str] | None:
    if len(args) >= 4:
        code, text = args[1], args[2]
    elif len(args) >= 2:
        code, text = args[0], args[1]
    else:
        return None
    try:
        return int(code), str(text)
    except (TypeError, ValueError):
        return None


def _finite_float(value: object) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if parsed != parsed or parsed in {float("inf"), float("-inf")}:
        return None
    return parsed


class _AccountSnapshotProbe(EWrapper, EClient):
    def __init__(self) -> None:
        EWrapper.__init__(self)
        EClient.__init__(self, self)
        self.connected_ready = Event()
        self.accounts_ready = Event()
        self.download_ready = Event()
        self.summary_ready = Event()
        self.accounts: list[str] = []
        self.account_ready = True
        self.account_values: dict[tuple[str, str], float] = {}
        self.summary_values: dict[tuple[str, str], float] = {}
        self.portfolio: list[IbkrBrokerPosition] = []
        self.errors: list[str] = []
        self.fatal_error: str | None = None

    def nextValidId(self, orderId: int) -> None:  # noqa: N802
        self.connected_ready.set()

    def managedAccounts(self, accountsList: str) -> None:  # noqa: N802
        self.accounts = [item.strip() for item in str(accountsList).split(",") if item.strip()]
        self.accounts_ready.set()

    def updateAccountValue(self, key: str, val: str, currency: str, accountName: str) -> None:  # noqa: N802
        normalized_key = str(key).strip()
        normalized_currency = str(currency).strip().upper()
        if normalized_key == "accountReady":
            self.account_ready = str(val).strip().lower() not in {"false", "0", "no"}
            return
        parsed = _finite_float(val)
        if parsed is not None:
            self.account_values[(normalized_key, normalized_currency)] = parsed

    def updatePortfolio(  # noqa: N802
        self,
        contract: Contract,
        position,
        marketPrice: float,
        marketValue: float,
        averageCost: float,
        unrealizedPNL: float,
        realizedPNL: float,
        accountName: str,
    ) -> None:
        quantity = _finite_float(position)
        if quantity is None or quantity == 0:
            return
        self.portfolio.append(
            IbkrBrokerPosition(
                symbol=str(getattr(contract, "symbol", "") or "").strip().upper(),
                sec_type=str(getattr(contract, "secType", "") or "").strip().upper(),
                currency=str(getattr(contract, "currency", "") or "").strip().upper(),
                exchange=str(
                    getattr(contract, "primaryExchange", "")
                    or getattr(contract, "exchange", "")
                    or ""
                ).strip().upper(),
                quantity=quantity,
                market_price=float(_finite_float(marketPrice) or 0.0),
                market_value=float(_finite_float(marketValue) or 0.0),
                average_cost=float(_finite_float(averageCost) or 0.0),
                unrealized_pnl=float(_finite_float(unrealizedPNL) or 0.0),
                realized_pnl=float(_finite_float(realizedPNL) or 0.0),
            )
        )

    def accountDownloadEnd(self, accountName: str) -> None:  # noqa: N802
        self.download_ready.set()

    def accountSummary(self, reqId, account, tag, value, currency):  # noqa: N802
        parsed = _finite_float(value)
        if parsed is None:
            return
        self.summary_values[(str(tag).strip(), str(currency).strip().upper())] = parsed

    def accountSummaryEnd(self, reqId: int) -> None:  # noqa: N802
        self.summary_ready.set()

    def error(self, reqId, *args):
        parsed = _parse_error(args)
        if parsed is None:
            return
        code, text = parsed
        message = f"{code}: {text}"
        self.errors.append(message)
        if code in {326, 502, 503, 504, 1100}:
            self.fatal_error = message
            self.connected_ready.set()
            self.accounts_ready.set()
            self.download_ready.set()
            self.summary_ready.set()


def _summary_value(probe: _AccountSnapshotProbe, tag: str, base_currency: str | None) -> float | None:
    if base_currency:
        value = probe.summary_values.get((tag, base_currency))
        if value is not None:
            return value
    value = probe.account_values.get((tag, "BASE"))
    if value is not None:
        return value
    matches = [value for (key, _currency), value in probe.summary_values.items() if key == tag]
    return matches[0] if len(matches) == 1 else None


def _base_currency(probe: _AccountSnapshotProbe) -> str | None:
    currencies = {
        currency
        for (tag, currency), value in probe.summary_values.items()
        if tag == "NetLiquidation"
        and value > 0
        and len(currency) == 3
        and currency.isalpha()
        and currency != "BASE"
    }
    return next(iter(currencies)) if len(currencies) == 1 else None


def preview_ibkr_paper_account_snapshot(*, timeout: float = 10.0) -> IbkrPaperAccountSnapshot:
    """Read one complete Paper account/portfolio snapshot, trying 4002 then 7497."""
    collected: list[str] = []
    for use_gateway in (True, False):
        cfg = create_ibkr_paper_config(use_gateway=use_gateway)
        probe = _AccountSnapshotProbe()
        try:
            try:
                probe.connect(cfg.host, cfg.port, cfg.client_id + 270)
            except OSError as exc:
                collected.append(f"{cfg.port}: {exc}")
                continue
            Thread(
                target=run_ibapi_message_loop_safely,
                kwargs={"client": probe, "errors": probe.errors},
                daemon=True,
            ).start()
            if not probe.connected_ready.wait(timeout) or probe.fatal_error:
                collected.extend(probe.errors)
                continue

            probe.reqManagedAccts()
            if not probe.accounts_ready.wait(timeout) or len(probe.accounts) != 1:
                collected.extend(probe.errors)
                collected.append(
                    f"{cfg.port}: expected exactly one managed Paper account; got {len(probe.accounts)}"
                )
                continue
            account_id = probe.accounts[0]

            probe.reqAccountUpdates(True, account_id)
            probe.reqAccountSummary(
                991,
                "All",
                "NetLiquidation,AvailableFunds,GrossPositionValue,TotalCashValue",
            )
            download_complete = probe.download_ready.wait(timeout)
            summary_complete = probe.summary_ready.wait(timeout)
            try:
                probe.cancelAccountSummary(991)
            except Exception:
                pass
            probe.reqAccountUpdates(False, account_id)

            if not download_complete or not summary_complete or probe.fatal_error:
                collected.extend(probe.errors)
                if not download_complete:
                    collected.append(
                        f"{cfg.port}: account download did not complete before timeout"
                    )
                if not summary_complete:
                    collected.append(
                        f"{cfg.port}: account summary did not complete before timeout"
                    )
                continue

            base_currency = _base_currency(probe)
            snapshot = IbkrPaperAccountSnapshot(
                connected=True,
                endpoint_port=cfg.port,
                account_id=account_id,
                account_ready=bool(probe.account_ready),
                base_currency=base_currency,
                net_liquidation=_summary_value(probe, "NetLiquidation", base_currency),
                available_funds=_summary_value(probe, "AvailableFunds", base_currency),
                gross_position_value=_summary_value(probe, "GrossPositionValue", base_currency),
                total_cash_value=_summary_value(probe, "TotalCashValue", base_currency),
                positions=tuple(probe.portfolio),
                order_sent=False,
                errors=tuple(collected + probe.errors),
            )
            return snapshot
        finally:
            if probe.isConnected():
                probe.disconnect()

    return IbkrPaperAccountSnapshot(
        connected=False,
        endpoint_port=None,
        account_id=None,
        account_ready=False,
        base_currency=None,
        net_liquidation=None,
        available_funds=None,
        gross_position_value=None,
        total_cash_value=None,
        positions=(),
        order_sent=False,
        errors=tuple(collected),
    )

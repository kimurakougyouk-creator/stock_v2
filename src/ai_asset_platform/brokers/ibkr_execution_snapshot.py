"""Read-only IBKR Paper execution history snapshot for reconciliation.

This module requests broker execution reports only. It never creates, changes,
cancels, or transmits an order. The goal is to recover broker-side execution
evidence when the durable local ledger and the current Paper account disagree.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from threading import Event, Thread

from ibapi.client import EClient
from ibapi.execution import ExecutionFilter
from ibapi.wrapper import EWrapper

from ai_asset_platform.brokers.ibkr_config import create_ibkr_paper_config
from ai_asset_platform.brokers.ibkr_thread_runner import run_ibapi_message_loop_safely


@dataclass(frozen=True)
class IbkrExecutionEvidence:
    exec_id: str
    order_id: int
    perm_id: int
    symbol: str
    sec_type: str
    currency: str
    exchange: str
    side: str
    quantity: float
    price: float
    time: str
    account: str
    con_id: int | None = None
    local_symbol: str | None = None
    expiry: str | None = None
    multiplier: str | None = None


@dataclass(frozen=True)
class IbkrPaperExecutionSnapshot:
    connected: bool
    endpoint_port: int | None
    executions: tuple[IbkrExecutionEvidence, ...] = ()
    order_sent: bool = False
    errors: tuple[str, ...] = field(default_factory=tuple)

    @property
    def ready(self) -> bool:
        return self.connected and not self.order_sent


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


class _ExecutionSnapshotProbe(EWrapper, EClient):
    def __init__(self) -> None:
        EWrapper.__init__(self)
        EClient.__init__(self, self)
        self.connected_ready = Event()
        self.executions_ready = Event()
        self.executions: list[IbkrExecutionEvidence] = []
        self.errors: list[str] = []
        self.fatal_error: str | None = None

    def nextValidId(self, orderId: int) -> None:  # noqa: N802
        self.connected_ready.set()

    def execDetails(self, reqId, contract, execution) -> None:  # noqa: N802
        raw_side = str(getattr(execution, "side", "") or "").strip().upper()
        side = {"BOT": "BUY", "SLD": "SELL"}.get(raw_side, raw_side)
        try:
            quantity = float(getattr(execution, "shares", 0.0) or 0.0)
            price = float(getattr(execution, "price", 0.0) or 0.0)
            order_id = int(getattr(execution, "orderId", 0) or 0)
            perm_id = int(getattr(execution, "permId", 0) or 0)
            raw_con_id = int(getattr(contract, "conId", 0) or 0)
        except (TypeError, ValueError):
            return
        if quantity <= 0 or price <= 0 or side not in {"BUY", "SELL"}:
            return
        local_symbol = str(getattr(contract, "localSymbol", "") or "").strip().upper() or None
        expiry = str(getattr(contract, "lastTradeDateOrContractMonth", "") or "").strip() or None
        multiplier = str(getattr(contract, "multiplier", "") or "").strip() or None
        self.executions.append(
            IbkrExecutionEvidence(
                exec_id=str(getattr(execution, "execId", "") or "").strip(),
                order_id=order_id,
                perm_id=perm_id,
                symbol=str(getattr(contract, "symbol", "") or "").strip().upper(),
                sec_type=str(getattr(contract, "secType", "") or "").strip().upper(),
                currency=str(getattr(contract, "currency", "") or "").strip().upper(),
                exchange=str(
                    getattr(execution, "exchange", "")
                    or getattr(contract, "primaryExchange", "")
                    or getattr(contract, "exchange", "")
                    or ""
                ).strip().upper(),
                side=side,
                quantity=quantity,
                price=price,
                time=str(getattr(execution, "time", "") or "").strip(),
                account=str(getattr(execution, "acctNumber", "") or "").strip(),
                con_id=raw_con_id if raw_con_id > 0 else None,
                local_symbol=local_symbol,
                expiry=expiry,
                multiplier=multiplier,
            )
        )

    def execDetailsEnd(self, reqId: int) -> None:  # noqa: N802
        self.executions_ready.set()

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
            self.executions_ready.set()


def preview_ibkr_paper_execution_snapshot(*, timeout: float = 10.0) -> IbkrPaperExecutionSnapshot:
    """Request available broker execution reports, auto-detecting 4002 then 7497."""
    collected: list[str] = []
    for use_gateway in (True, False):
        cfg = create_ibkr_paper_config(use_gateway=use_gateway)
        probe = _ExecutionSnapshotProbe()
        try:
            try:
                probe.connect(cfg.host, cfg.port, cfg.client_id + 271)
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

            probe.reqExecutions(992, ExecutionFilter())
            if not probe.executions_ready.wait(timeout) or probe.fatal_error:
                collected.extend(probe.errors)
                continue

            deduped: dict[str, IbkrExecutionEvidence] = {}
            anonymous: list[IbkrExecutionEvidence] = []
            for item in probe.executions:
                if item.exec_id:
                    deduped.setdefault(item.exec_id, item)
                else:
                    anonymous.append(item)
            executions = tuple(deduped.values()) + tuple(anonymous)
            return IbkrPaperExecutionSnapshot(
                connected=True,
                endpoint_port=cfg.port,
                executions=executions,
                order_sent=False,
                errors=tuple(collected + probe.errors),
            )
        finally:
            if probe.isConnected():
                probe.disconnect()

    return IbkrPaperExecutionSnapshot(
        connected=False,
        endpoint_port=None,
        executions=(),
        order_sent=False,
        errors=tuple(collected),
    )


def main() -> int:
    result = preview_ibkr_paper_execution_snapshot()
    print("===== IBKR PAPER EXECUTION SNAPSHOT =====")
    print("CONNECTED       :", result.connected)
    print("ENDPOINT PORT   :", result.endpoint_port)
    print("EXECUTION COUNT :", len(result.executions))
    print("ORDER SENT      :", result.order_sent)
    for index, item in enumerate(result.executions, start=1):
        print(
            f"EXECUTION {index}: symbol={item.symbol} local_symbol={item.local_symbol or 'UNKNOWN'} "
            f"sec_type={item.sec_type or 'UNKNOWN'} side={item.side} qty={item.quantity:g} "
            f"price={item.price:g} currency={item.currency or 'UNKNOWN'} exchange={item.exchange or 'UNKNOWN'} "
            f"con_id={item.con_id or 'UNKNOWN'} expiry={item.expiry or 'UNKNOWN'} multiplier={item.multiplier or 'UNKNOWN'} "
            f"order_id={item.order_id} perm_id={item.perm_id} exec_id={item.exec_id or 'UNKNOWN'} time={item.time or 'UNKNOWN'}"
        )
    print("ERRORS          :", list(result.errors))
    print("REAL ORDER SENT : False")
    return 0 if result.ready else 1


if __name__ == "__main__":
    raise SystemExit(main())

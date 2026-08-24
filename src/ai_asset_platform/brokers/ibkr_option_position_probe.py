"""Read-only broker position probe for the pinned SPY option contract.

This module never creates an Order and is safe to run after an uncertain Paper
E2E outcome. It connects to IBKR Paper, requests positions, deduplicates
identical callbacks, fails closed on conflicting duplicate quantities, and
reports the current quantity for the exact pinned option identity.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from threading import Event, Thread

from ibapi.client import EClient
from ibapi.wrapper import EWrapper

from ai_asset_platform.brokers.ibkr_config import create_ibkr_paper_config
from ai_asset_platform.brokers.ibkr_option_paper_roundtrip import LOCAL_SYMBOL
from ai_asset_platform.brokers.ibkr_thread_runner import run_ibapi_message_loop_safely
from ai_asset_platform.core.settings import SETTINGS


@dataclass(frozen=True)
class OptionPositionProbeResult:
    connected: bool
    endpoint_port: int | None
    local_symbol: str
    quantity: float | None
    flat: bool
    errors: tuple[str, ...] = field(default_factory=tuple)
    real_order_sent: bool = False
    live_order_sent: bool = False


class _Probe(EWrapper, EClient):
    def __init__(self) -> None:
        EWrapper.__init__(self)
        EClient.__init__(self, self)
        self.ready = Event()
        self.position_ready = Event()
        self.positions: list[tuple[str, str, float]] = []
        self.errors: list[str] = []

    def nextValidId(self, orderId: int) -> None:  # noqa: N802
        self.ready.set()

    def position(self, account, contract, pos, avgCost) -> None:  # noqa: N802
        self.positions.append(
            (
                str(getattr(contract, "localSymbol", "") or "").upper(),
                str(getattr(contract, "secType", "") or "").upper(),
                float(pos),
            )
        )

    def positionEnd(self) -> None:  # noqa: N802
        self.position_ready.set()

    def error(self, reqId, errorTime, errorCode, errorString, advancedOrderRejectJson="") -> None:
        self.errors.append(f"{errorCode}: {errorString}")
        if int(errorCode) in {502, 503, 504, 1100}:
            self.ready.set()
            self.position_ready.set()


def _quantity(rows: list[tuple[str, str, float]]) -> float:
    matches = [
        qty
        for local, sec_type, qty in rows
        if local == LOCAL_SYMBOL.upper() and sec_type == "OPT"
    ]
    if not matches:
        return 0.0
    first = float(matches[0])
    if any(abs(float(qty) - first) > 1e-9 for qty in matches[1:]):
        raise RuntimeError("conflicting duplicate SPY option position callbacks")
    return first


def probe_option_position(*, timeout: float = 15.0) -> OptionPositionProbeResult:
    if not SETTINGS.enable_ibkr_paper:
        return OptionPositionProbeResult(False, None, LOCAL_SYMBOL, None, False, ("IBKR Paper is not explicitly enabled",))
    if SETTINGS.enable_live_trading or SETTINGS.live_trading_unlocked:
        return OptionPositionProbeResult(False, None, LOCAL_SYMBOL, None, False, ("Live Trading safety lock is not intact",))

    cfg = create_ibkr_paper_config(use_gateway=True)
    probe = _Probe()
    try:
        probe.connect(cfg.host, cfg.port, cfg.client_id + 297)
        Thread(
            target=run_ibapi_message_loop_safely,
            kwargs={"client": probe, "errors": probe.errors},
            daemon=True,
        ).start()
        if not probe.ready.wait(timeout):
            return OptionPositionProbeResult(False, cfg.port, LOCAL_SYMBOL, None, False, tuple(probe.errors))
        probe.positions.clear()
        probe.position_ready.clear()
        probe.reqPositions()
        if not probe.position_ready.wait(timeout):
            return OptionPositionProbeResult(True, cfg.port, LOCAL_SYMBOL, None, False, tuple(probe.errors))
        try:
            qty = _quantity(probe.positions)
        except RuntimeError as exc:
            return OptionPositionProbeResult(True, cfg.port, LOCAL_SYMBOL, None, False, tuple(probe.errors + [str(exc)]))
        finally:
            probe.cancelPositions()
        return OptionPositionProbeResult(
            True,
            cfg.port,
            LOCAL_SYMBOL,
            qty,
            abs(qty) <= 1e-9,
            tuple(probe.errors),
            False,
            False,
        )
    finally:
        if probe.isConnected():
            probe.disconnect()


def main() -> int:
    result = probe_option_position()
    print("===== IBKR PAPER SPY OPTION POSITION PROBE =====")
    print("CONNECTED             :", result.connected)
    print("ENDPOINT PORT         :", result.endpoint_port)
    print("LOCAL SYMBOL          :", result.local_symbol)
    print("QUANTITY              :", result.quantity)
    print("FLAT                  :", result.flat)
    print("ERRORS                :", list(result.errors))
    print("REAL ORDER SENT       :", result.real_order_sent)
    print("LIVE ORDER SENT       :", result.live_order_sent)
    return 0 if result.connected and result.quantity is not None and not result.real_order_sent and not result.live_order_sent else 2


if __name__ == "__main__":
    raise SystemExit(main())

"""Read-only IBKR Paper FX API handshake diagnostics.

This diagnostic goes one step beyond the TCP socket probe: it performs an
EClient.connect()/nextValidId handshake against the already-open Paper Gateway
endpoint only. It never requests contracts, market data, account data, orders,
positions, executions, or What-If/real orders.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from threading import Event

from ibapi.client import EClient
from ibapi.wrapper import EWrapper

from ai_asset_platform.brokers.ibkr_config import create_ibkr_paper_config
from ai_asset_platform.brokers.ibkr_probe_thread import start_guarded_ibapi_loop


@dataclass(frozen=True)
class IbkrFxHandshakeDiagnosticResult:
    connected: bool
    next_valid_id_received: bool
    endpoint_port: int
    client_id: int
    server_version: int | None
    real_order_sent: bool = False
    live_order_sent: bool = False
    errors: tuple[str, ...] = field(default_factory=tuple)

    @property
    def ready(self) -> bool:
        return self.connected and self.next_valid_id_received and not self.errors


class _HandshakeProbe(EWrapper, EClient):
    def __init__(self) -> None:
        EWrapper.__init__(self)
        EClient.__init__(self, self)
        self.ready = Event()
        self.next_order_id: int | None = None
        self.errors: list[str] = []

    def nextValidId(self, orderId: int) -> None:  # noqa: N802
        self.next_order_id = int(orderId)
        self.ready.set()

    def error(self, reqId, *args):
        if len(args) >= 3:
            error_code, error_string = args[-3], args[-2]
        elif len(args) >= 2:
            error_code, error_string = args[0], args[1]
        else:
            return
        try:
            code = int(error_code)
        except (TypeError, ValueError):
            return
        # Farm connection/status messages are informational and must not turn a
        # successful API handshake into a false failure.
        if code in {2104, 2106, 2107, 2108, 2158}:
            return
        self.errors.append(f"{code}: {error_string}")
        if code in {326, 502, 503, 504, 1100}:
            self.ready.set()


def diagnose_ibkr_paper_gateway_handshake(timeout: float = 8.0) -> IbkrFxHandshakeDiagnosticResult:
    cfg = create_ibkr_paper_config(use_gateway=True)
    cfg.validate()
    if cfg.port != 4002 or not cfg.paper_trading or cfg.allow_live_trading:
        raise RuntimeError("Handshake diagnostic requires IB Gateway Paper 4002 with Live disabled")

    client_id = cfg.client_id + 242
    probe = _HandshakeProbe()
    thread = None
    state = None
    try:
        try:
            probe.connect(cfg.host, cfg.port, client_id)
        except OSError as exc:
            return IbkrFxHandshakeDiagnosticResult(
                connected=False,
                next_valid_id_received=False,
                endpoint_port=cfg.port,
                client_id=client_id,
                server_version=None,
                errors=(str(exc),),
            )
        thread, state = start_guarded_ibapi_loop(
            probe.run, name=f"ibkr-fx-handshake-{cfg.port}"
        )
        probe.ready.wait(timeout)
        errors = list(probe.errors)
        if state is not None and state.exception:
            errors.append(f"message-loop {state.exception}")
        version = None
        try:
            raw_version = probe.serverVersion()
            version = int(raw_version) if raw_version is not None else None
        except (TypeError, ValueError):
            version = None
        return IbkrFxHandshakeDiagnosticResult(
            connected=probe.isConnected(),
            next_valid_id_received=probe.next_order_id is not None,
            endpoint_port=cfg.port,
            client_id=client_id,
            server_version=version,
            errors=tuple(errors),
        )
    finally:
        if probe.isConnected():
            probe.disconnect()
        if thread is not None:
            thread.join(timeout=1.0)


def main() -> int:
    result = diagnose_ibkr_paper_gateway_handshake()
    print("===== IBKR PAPER FX HANDSHAKE DIAGNOSTICS =====")
    print("ENDPOINT PORT          :", result.endpoint_port)
    print("CLIENT ID              :", result.client_id)
    print("CONNECTED              :", result.connected)
    print("NEXT VALID ID RECEIVED :", result.next_valid_id_received)
    print("SERVER VERSION         :", result.server_version)
    print("ERRORS                 :", list(result.errors))
    print("HANDSHAKE READY        :", result.ready)
    print("REAL ORDER SENT        : False")
    print("LIVE ORDER SENT        : False")
    return 0 if result.ready else 1


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

from dataclasses import dataclass, field
import socket

from ai_asset_platform.brokers.ibkr_config import create_ibkr_paper_config


@dataclass(frozen=True)
class FxPaperConnectionDiagnostics:
    host: str
    gateway_port: int
    tws_port: int
    gateway_open: bool
    tws_open: bool
    errors: tuple[str, ...] = field(default_factory=tuple)

    @property
    def any_paper_endpoint_open(self) -> bool:
        return self.gateway_open or self.tws_open


def _port_open(host: str, port: int, *, timeout: float = 1.5) -> tuple[bool, str | None]:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True, None
    except OSError as exc:
        return False, str(exc)


def diagnose_fx_paper_connection(*, timeout: float = 1.5) -> FxPaperConnectionDiagnostics:
    gateway = create_ibkr_paper_config(use_gateway=True)
    tws = create_ibkr_paper_config(use_gateway=False)
    gateway_open, gateway_error = _port_open(gateway.host, gateway.port, timeout=timeout)
    tws_open, tws_error = _port_open(tws.host, tws.port, timeout=timeout)
    errors: list[str] = []
    if gateway_error:
        errors.append(f"{gateway.host}:{gateway.port} {gateway_error}")
    if tws_error:
        errors.append(f"{tws.host}:{tws.port} {tws_error}")
    return FxPaperConnectionDiagnostics(
        host=gateway.host,
        gateway_port=gateway.port,
        tws_port=tws.port,
        gateway_open=gateway_open,
        tws_open=tws_open,
        errors=tuple(errors),
    )


def main() -> int:
    result = diagnose_fx_paper_connection()
    print("===== IBKR PAPER FX CONNECTION DIAGNOSTICS =====")
    print("HOST                  :", result.host)
    print("GATEWAY PAPER PORT    :", result.gateway_port)
    print("GATEWAY PORT OPEN     :", result.gateway_open)
    print("TWS PAPER PORT        :", result.tws_port)
    print("TWS PORT OPEN         :", result.tws_open)
    print("ERRORS                :", list(result.errors))
    print("PAPER ENDPOINT OPEN   :", result.any_paper_endpoint_open)
    print("REAL ORDER SENT       : False")
    print("LIVE ORDER SENT       : False")
    return 0 if result.any_paper_endpoint_open else 1


if __name__ == "__main__":
    raise SystemExit(main())

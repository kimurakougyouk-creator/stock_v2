from __future__ import annotations

import socket
from dataclasses import dataclass

from ai_asset_platform.brokers.ibkr_config import create_ibkr_paper_config
from ai_asset_platform.brokers.ibkr_diagnostics import diagnose_ibkr_environment


@dataclass(frozen=True)
class IbkrPreflightResult:
    status: str
    api_ready: bool
    tws_port_open: bool
    host: str
    port: int
    message: str


def _is_port_open(host: str, port: int, timeout: float = 1.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def run_ibkr_paper_preflight(
    timeout: float = 1.0,
    *,
    use_gateway: bool = True,
) -> IbkrPreflightResult:
    """IBKR Paper接続前の安全な自動診断。注文は一切送信しない。

    use_gateway=True (デフォルト) はIB Gateway Paper Trading (127.0.0.1:4002)、
    use_gateway=False はTWS Paper Trading (127.0.0.1:7497) を確認する。
    """
    config = create_ibkr_paper_config(use_gateway=use_gateway)
    diagnostic = diagnose_ibkr_environment()
    app_name = "IB Gateway" if use_gateway else "TWS"

    api_ready = diagnostic.status == "READY"
    tws_port_open = _is_port_open(config.host, config.port, timeout)

    if not api_ready:
        return IbkrPreflightResult(
            status="NOT_READY",
            api_ready=False,
            tws_port_open=tws_port_open,
            host=config.host,
            port=config.port,
            message=diagnostic.message,
        )

    if not tws_port_open:
        return IbkrPreflightResult(
            status="WAITING_FOR_GATEWAY" if use_gateway else "WAITING_FOR_TWS",
            api_ready=True,
            tws_port_open=False,
            host=config.host,
            port=config.port,
            message=(
                f"Python APIは準備完了です。"
                f"{app_name} Paper API {config.host}:{config.port} はまだ待受していません。"
                f"{app_name}のPaper TradingログインとAPI設定を確認してください。"
            ),
        )

    return IbkrPreflightResult(
        status="READY_TO_CONNECT",
        api_ready=True,
        tws_port_open=True,
        host=config.host,
        port=config.port,
        message=(
            f"IBKR Paper API {config.host}:{config.port} への"
            "接続準備ができています。"
        ),
    )


def main() -> None:
    result = run_ibkr_paper_preflight()

    print("===== IBKR PAPER PREFLIGHT =====")
    print(f"STATUS       : {result.status}")
    print(f"API READY    : {result.api_ready}")
    print(f"IBKR PORT OPEN: {result.tws_port_open}")
    print(f"HOST         : {result.host}")
    print(f"PORT         : {result.port}")
    print(f"MESSAGE      : {result.message}")


if __name__ == "__main__":
    main()

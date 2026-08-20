from __future__ import annotations

from dataclasses import dataclass

from ai_asset_platform.brokers.ibkr_config import create_ibkr_paper_config
from ai_asset_platform.brokers.ibkr_connection import probe_ibkr_paper_connection
from ai_asset_platform.brokers.ibkr_paper_order_guard import validate_ibkr_paper_test_order
from ai_asset_platform.brokers.ibkr_preflight import run_ibkr_paper_preflight


@dataclass(frozen=True)
class IbkrPaperSmokeTestResult:
    status: str
    preflight_status: str
    guard_status: str
    connected: bool
    next_order_id: int | None
    order_sent: bool
    message: str


def run_ibkr_paper_smoke_test(*, timeout: float = 5.0) -> IbkrPaperSmokeTestResult:
    """Run the complete non-transmitting IBKR Gateway Paper smoke test."""
    config = create_ibkr_paper_config(use_gateway=True)
    config.validate()

    if not config.paper_trading or config.allow_live_trading:
        return IbkrPaperSmokeTestResult(
            status="SAFETY_BLOCKED",
            preflight_status="NOT_RUN",
            guard_status="NOT_RUN",
            connected=False,
            next_order_id=None,
            order_sent=False,
            message="Paper-only safety configuration is not active.",
        )

    preflight = run_ibkr_paper_preflight(timeout=timeout, use_gateway=True)
    if preflight.status != "READY_TO_CONNECT":
        return IbkrPaperSmokeTestResult(
            status="PREFLIGHT_BLOCKED",
            preflight_status=preflight.status,
            guard_status="NOT_RUN",
            connected=False,
            next_order_id=None,
            order_sent=False,
            message=preflight.message,
        )

    guard = validate_ibkr_paper_test_order(
        "AAPL", 1, preflight=preflight, use_gateway=True
    )
    if not guard.allowed:
        return IbkrPaperSmokeTestResult(
            status="GUARD_BLOCKED",
            preflight_status=preflight.status,
            guard_status=guard.status,
            connected=False,
            next_order_id=None,
            order_sent=False,
            message=guard.message,
        )

    connection = probe_ibkr_paper_connection(config, timeout=timeout)
    if not connection.connected:
        return IbkrPaperSmokeTestResult(
            status="CONNECTION_FAILED",
            preflight_status=preflight.status,
            guard_status=guard.status,
            connected=False,
            next_order_id=None,
            order_sent=False,
            message=connection.message,
        )

    return IbkrPaperSmokeTestResult(
        status="READY_FOR_MINIMAL_PAPER_ORDER",
        preflight_status=preflight.status,
        guard_status=guard.status,
        connected=True,
        next_order_id=connection.next_order_id,
        order_sent=False,
        message=(
            "IBKR Gateway Paper API handshake succeeded. "
            "Safety guard passed. No order was transmitted."
        ),
    )


def main() -> None:
    result = run_ibkr_paper_smoke_test()
    print("===== IBKR PAPER ONE-SHOT SMOKE TEST =====")
    print(f"STATUS          : {result.status}")
    print(f"PREFLIGHT STATUS: {result.preflight_status}")
    print(f"GUARD STATUS    : {result.guard_status}")
    print(f"CONNECTED       : {result.connected}")
    print(f"NEXT ORDER ID   : {result.next_order_id}")
    print(f"ORDER SENT      : {result.order_sent}")
    print(f"MESSAGE         : {result.message}")


if __name__ == "__main__":
    main()

"""Explicit read-only FX evidence from the IBKR Live session.

This module is preparation-only. It never places, previews, changes, cancels,
retries, or closes an order and never enables Live Trading. An exact read-only
confirmation is required before a Live socket is opened.

Evidence order:
1. Live CASH/IDEALPRO bid/ask snapshot.
2. Delayed market-data bid/ask snapshot.
3. Delayed-frozen market-data bid/ask snapshot.
4. Live-account ExchangeRate from read-only account updates.

Missing evidence fails closed; no FX rate is guessed.
"""
from __future__ import annotations

from dataclasses import asdict
import json
import os
from pathlib import Path
from threading import Thread

from ai_asset_platform.brokers.ibkr_fx_discovery import build_fx_discovery_contract
from ai_asset_platform.brokers.ibkr_fx_snapshot import (
    IbkrFxSnapshotResult,
    _AccountFxProbe,
    _FxSnapshotProbe,
    _midpoint,
)
from ai_asset_platform.brokers.ibkr_live_readonly_account import (
    CONFIRMATION_ENV,
    CONFIRMATION_VALUE,
    LIVE_GATEWAY_PORT,
    LIVE_TWS_PORT,
)
from ai_asset_platform.brokers.ibkr_thread_runner import run_ibapi_message_loop_safely


DEFAULT_REPORT_PATH = Path("results/ibkr_live_fx_evidence_latest.json")
REPORT_SCHEMA_VERSION = 1


def _blocked(base: str, quote: str, reason: str) -> IbkrFxSnapshotResult:
    return IbkrFxSnapshotResult(
        connected=False,
        endpoint_port=None,
        base_currency=base,
        quote_currency=quote,
        exchange="UNAVAILABLE",
        bid=None,
        ask=None,
        rate=None,
        source="BLOCKED",
        order_sent=False,
        errors=(reason,),
    )


def _validate_pair(base_currency: str, quote_currency: str) -> tuple[str, str]:
    base = str(base_currency or "").strip().upper()
    quote = str(quote_currency or "").strip().upper()
    if len(base) != 3 or len(quote) != 3 or not base.isalpha() or not quote.isalpha():
        raise ValueError("base/quote must be 3-letter currency codes")
    return base, quote


def _request_live_market_snapshot(
    *,
    base_currency: str,
    quote_currency: str,
    market_data_type: int,
    timeout: float,
) -> IbkrFxSnapshotResult:
    contract = build_fx_discovery_contract(
        base_currency=base_currency,
        quote_currency=quote_currency,
        exchange="IDEALPRO",
    )
    source = {
        1: "LIVE_MARKET_DATA",
        3: "LIVE_SESSION_DELAYED_MARKET_DATA",
        4: "LIVE_SESSION_DELAYED_FROZEN_MARKET_DATA",
    }.get(int(market_data_type), f"LIVE_SESSION_MARKET_DATA_{market_data_type}")
    collected: list[str] = []
    offset = {1: 560, 3: 563, 4: 564}.get(int(market_data_type), 565)

    for index, port in enumerate((LIVE_GATEWAY_PORT, LIVE_TWS_PORT), start=1):
        probe = _FxSnapshotProbe()
        try:
            try:
                probe.connect("127.0.0.1", port, offset + index)
            except OSError as exc:
                collected.append(f"{port}: {exc}")
                continue
            Thread(
                target=run_ibapi_message_loop_safely,
                kwargs={"client": probe, "errors": probe.errors},
                daemon=True,
            ).start()
            if not probe.connected_ready.wait(timeout) or probe.fatal_error:
                collected.extend(probe.errors)
                continue
            if int(market_data_type) != 1:
                probe.reqMarketDataType(int(market_data_type))
            probe.reqMktData(1501, contract, "", True, False, [])
            probe.snapshot_ready.wait(timeout)
            rate = _midpoint(probe.bid, probe.ask)
            if rate is not None:
                return IbkrFxSnapshotResult(
                    connected=True,
                    endpoint_port=port,
                    base_currency=base_currency,
                    quote_currency=quote_currency,
                    exchange="IDEALPRO",
                    bid=probe.bid,
                    ask=probe.ask,
                    rate=rate,
                    source=source,
                    order_sent=False,
                    errors=tuple(collected + probe.errors),
                )
            collected.extend(probe.errors)
        finally:
            if probe.isConnected():
                probe.disconnect()

    return IbkrFxSnapshotResult(
        connected=False,
        endpoint_port=None,
        base_currency=base_currency,
        quote_currency=quote_currency,
        exchange="IDEALPRO",
        bid=None,
        ask=None,
        rate=None,
        source=source,
        order_sent=False,
        errors=tuple(collected),
    )


def _request_live_account_fx(
    *, base_currency: str, quote_currency: str, timeout: float,
) -> IbkrFxSnapshotResult:
    collected: list[str] = []
    for index, port in enumerate((LIVE_GATEWAY_PORT, LIVE_TWS_PORT), start=1):
        probe = _AccountFxProbe(currency=base_currency)
        try:
            try:
                probe.connect("127.0.0.1", port, 570 + index)
            except OSError as exc:
                collected.append(f"{port}: {exc}")
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
            if not probe.account_ready.wait(timeout) or not probe.account_id:
                collected.extend(probe.errors)
                collected.append(f"{port}: managed Live account unavailable")
                continue
            probe.reqAccountUpdates(True, probe.account_id)
            probe.fx_ready.wait(timeout)
            probe.reqAccountUpdates(False, probe.account_id)
            if probe.rate is not None and float(probe.rate) > 0:
                return IbkrFxSnapshotResult(
                    connected=True,
                    endpoint_port=port,
                    base_currency=base_currency,
                    quote_currency=quote_currency,
                    exchange="ACCOUNT",
                    bid=None,
                    ask=None,
                    rate=float(probe.rate),
                    source="LIVE_ACCOUNT_EXCHANGE_RATE",
                    order_sent=False,
                    errors=tuple(collected + probe.errors),
                )
            collected.extend(probe.errors)
            collected.append(
                f"{port}: Live account ExchangeRate for {base_currency}->{quote_currency} unavailable"
            )
        finally:
            if probe.isConnected():
                probe.disconnect()

    return IbkrFxSnapshotResult(
        connected=False,
        endpoint_port=None,
        base_currency=base_currency,
        quote_currency=quote_currency,
        exchange="ACCOUNT",
        bid=None,
        ask=None,
        rate=None,
        source="LIVE_ACCOUNT_EXCHANGE_RATE",
        order_sent=False,
        errors=tuple(collected),
    )


def resolve_ibkr_live_fx_evidence(
    *,
    base_currency: str,
    quote_currency: str,
    timeout: float = 10.0,
    confirmation: str | None = None,
) -> IbkrFxSnapshotResult:
    """Resolve Live-session FX evidence without any order API request."""
    if timeout <= 0:
        raise ValueError("timeout must be positive")
    base, quote = _validate_pair(base_currency, quote_currency)
    supplied = (
        str(confirmation).strip()
        if confirmation is not None
        else os.getenv(CONFIRMATION_ENV, "").strip()
    )
    if supplied != CONFIRMATION_VALUE:
        return _blocked(base, quote, "exact Live read-only confirmation is missing")
    if base == quote:
        return IbkrFxSnapshotResult(
            connected=True,
            endpoint_port=None,
            base_currency=base,
            quote_currency=quote,
            exchange="IDENTITY",
            bid=1.0,
            ask=1.0,
            rate=1.0,
            source="IDENTITY",
            order_sent=False,
            errors=(),
        )

    errors: list[str] = []
    for market_data_type in (1, 3, 4):
        market = _request_live_market_snapshot(
            base_currency=base,
            quote_currency=quote,
            market_data_type=market_data_type,
            timeout=timeout,
        )
        if market.ready:
            return IbkrFxSnapshotResult(
                connected=market.connected,
                endpoint_port=market.endpoint_port,
                base_currency=market.base_currency,
                quote_currency=market.quote_currency,
                exchange=market.exchange,
                bid=market.bid,
                ask=market.ask,
                rate=market.rate,
                source=market.source,
                order_sent=False,
                errors=tuple(errors + list(market.errors)),
            )
        errors.extend(market.errors)

    account = _request_live_account_fx(
        base_currency=base,
        quote_currency=quote,
        timeout=timeout,
    )
    return IbkrFxSnapshotResult(
        connected=account.connected,
        endpoint_port=account.endpoint_port,
        base_currency=base,
        quote_currency=quote,
        exchange=account.exchange,
        bid=account.bid,
        ask=account.ask,
        rate=account.rate,
        source=account.source,
        order_sent=False,
        errors=tuple(errors + list(account.errors)),
    )


def persist_live_fx_evidence(
    result: IbkrFxSnapshotResult,
    *, report_path: Path = DEFAULT_REPORT_PATH,
) -> None:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": REPORT_SCHEMA_VERSION,
        **asdict(result),
        "ready": result.ready,
        "connection_mode": "LIVE_READ_ONLY",
        "broker_connection_used": result.source not in {"BLOCKED", "IDENTITY"},
        "order_sent": False,
        "live_order_sent": False,
    }
    temporary = report_path.with_suffix(report_path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(report_path)


def main() -> int:
    result = resolve_ibkr_live_fx_evidence(
        base_currency="USD",
        quote_currency="JPY",
    )
    persist_live_fx_evidence(result)
    print("===== IBKR LIVE FX EVIDENCE — READ ONLY =====")
    print("PAIR            : USD/JPY")
    print("READY           :", result.ready)
    print("ENDPOINT PORT   :", result.endpoint_port)
    print("SOURCE          :", result.source)
    print("RATE            :", result.rate)
    print("ORDER SENT      : False")
    print("LIVE ORDER SENT : False")
    print("REPORT          :", DEFAULT_REPORT_PATH)
    return 0 if result.ready else 1


if __name__ == "__main__":
    raise SystemExit(main())

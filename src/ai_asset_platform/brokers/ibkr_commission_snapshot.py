"""Read-only IBKR Paper commission evidence keyed by execution ID.

The snapshot requests historical executions only so IBKR can emit the matching
``commissionReport`` callbacks. It never creates, changes, cancels, retries, or
transmits an order. Missing commission evidence remains missing; nothing is
estimated or back-filled.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
import math
from pathlib import Path
from threading import Event, Thread
import time
from typing import Iterable

from ibapi.client import EClient
from ibapi.execution import ExecutionFilter
from ibapi.wrapper import EWrapper

from ai_asset_platform.brokers.ibkr_config import create_ibkr_paper_config
from ai_asset_platform.brokers.ibkr_thread_runner import run_ibapi_message_loop_safely


DEFAULT_REPORT_PATH = Path("results/ibkr_paper_commission_evidence_latest.json")
REPORT_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class IbkrCommissionEvidence:
    exec_id: str
    commission: float
    currency: str
    realized_pnl: float | None
    yield_value: float | None
    yield_redemption_date: int | None


@dataclass(frozen=True)
class IbkrPaperCommissionSnapshot:
    connected: bool
    endpoint_port: int | None
    commissions: tuple[IbkrCommissionEvidence, ...] = ()
    duplicate_conflicts: tuple[str, ...] = ()
    order_sent: bool = False
    errors: tuple[str, ...] = field(default_factory=tuple)

    @property
    def ready(self) -> bool:
        return (
            self.connected
            and not self.duplicate_conflicts
            and not self.order_sent
        )


@dataclass(frozen=True)
class CommissionMatchResult:
    ready: bool
    commissions: tuple[IbkrCommissionEvidence, ...]
    missing_exec_ids: tuple[str, ...]
    blockers: tuple[str, ...]


def _finite_or_none(value: object) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


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


class _CommissionSnapshotProbe(EWrapper, EClient):
    def __init__(self) -> None:
        EWrapper.__init__(self)
        EClient.__init__(self, self)
        self.connected_ready = Event()
        self.executions_ready = Event()
        self.commissions: list[IbkrCommissionEvidence] = []
        self.errors: list[str] = []
        self.fatal_error: str | None = None

    def nextValidId(self, orderId: int) -> None:  # noqa: N802
        self.connected_ready.set()

    def execDetails(self, reqId, contract, execution) -> None:  # noqa: N802
        # The execution stream is requested only to cause the corresponding
        # commissionReport callbacks. No order/execution is mutated here.
        return None

    def commissionReport(self, commissionReport) -> None:  # noqa: N802
        exec_id = str(getattr(commissionReport, "execId", "") or "").strip()
        commission = _finite_or_none(getattr(commissionReport, "commission", None))
        currency = str(getattr(commissionReport, "currency", "") or "").strip().upper()
        if not exec_id:
            self.errors.append("commission report is missing exec_id")
            return
        if commission is None:
            self.errors.append(f"commission report {exec_id} has invalid commission")
            return
        if len(currency) != 3 or not currency.isalpha():
            self.errors.append(f"commission report {exec_id} has invalid currency")
            return

        raw_redemption = getattr(commissionReport, "yieldRedemptionDate", None)
        try:
            redemption = int(raw_redemption)
        except (TypeError, ValueError):
            redemption = None
        if redemption is not None and redemption <= 0:
            redemption = None

        self.commissions.append(
            IbkrCommissionEvidence(
                exec_id=exec_id,
                commission=commission,
                currency=currency,
                realized_pnl=_finite_or_none(
                    getattr(commissionReport, "realizedPNL", None)
                ),
                yield_value=_finite_or_none(
                    getattr(commissionReport, "yield_", None)
                ),
                yield_redemption_date=redemption,
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


def _dedupe_commissions(
    rows: Iterable[IbkrCommissionEvidence],
) -> tuple[tuple[IbkrCommissionEvidence, ...], tuple[str, ...]]:
    by_exec: dict[str, IbkrCommissionEvidence] = {}
    conflicts: list[str] = []
    for row in rows:
        previous = by_exec.get(row.exec_id)
        if previous is None:
            by_exec[row.exec_id] = row
            continue
        if previous != row:
            conflicts.append(
                f"conflicting commission reports for exec_id={row.exec_id}"
            )
    return tuple(by_exec.values()), tuple(dict.fromkeys(conflicts))


def preview_ibkr_paper_commission_snapshot(
    *, timeout: float = 10.0, settle_seconds: float = 0.25,
) -> IbkrPaperCommissionSnapshot:
    """Read available Paper commission reports via ``reqExecutions`` only."""
    if timeout <= 0:
        raise ValueError("timeout must be positive")
    if settle_seconds < 0 or settle_seconds > 2:
        raise ValueError("settle_seconds must be from 0 to 2")

    collected: list[str] = []
    for use_gateway in (True, False):
        cfg = create_ibkr_paper_config(use_gateway=use_gateway)
        probe = _CommissionSnapshotProbe()
        try:
            try:
                probe.connect(cfg.host, cfg.port, cfg.client_id + 273)
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

            probe.reqExecutions(994, ExecutionFilter())
            if not probe.executions_ready.wait(timeout) or probe.fatal_error:
                collected.extend(probe.errors)
                continue

            # IBKR has no separate commission-report-end callback. Keep the
            # socket open for a tiny bounded settle interval after execDetailsEnd
            # so already-queued commission callbacks can be consumed.
            if settle_seconds:
                time.sleep(settle_seconds)

            commissions, conflicts = _dedupe_commissions(probe.commissions)
            return IbkrPaperCommissionSnapshot(
                connected=True,
                endpoint_port=cfg.port,
                commissions=commissions,
                duplicate_conflicts=conflicts,
                order_sent=False,
                errors=tuple(collected + probe.errors),
            )
        finally:
            if probe.isConnected():
                probe.disconnect()

    return IbkrPaperCommissionSnapshot(
        connected=False,
        endpoint_port=None,
        commissions=(),
        duplicate_conflicts=(),
        order_sent=False,
        errors=tuple(collected),
    )


def match_commissions_to_exec_ids(
    snapshot: IbkrPaperCommissionSnapshot,
    exec_ids: Iterable[object],
) -> CommissionMatchResult:
    requested: list[str] = []
    for value in exec_ids:
        exec_id = str(value or "").strip()
        if exec_id and exec_id not in requested:
            requested.append(exec_id)

    blockers: list[str] = []
    if not snapshot.ready:
        blockers.append("commission snapshot is not ready")
    by_exec = {row.exec_id: row for row in snapshot.commissions}
    matched = tuple(by_exec[exec_id] for exec_id in requested if exec_id in by_exec)
    missing = tuple(exec_id for exec_id in requested if exec_id not in by_exec)
    if missing:
        blockers.append("missing commission evidence for broker execution IDs")
    if not requested:
        blockers.append("no broker execution IDs were supplied")

    return CommissionMatchResult(
        ready=not blockers,
        commissions=matched,
        missing_exec_ids=missing,
        blockers=tuple(blockers),
    )


def persist_commission_snapshot(
    snapshot: IbkrPaperCommissionSnapshot,
    *, report_path: Path = DEFAULT_REPORT_PATH,
) -> None:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "connected": snapshot.connected,
        "endpoint_port": snapshot.endpoint_port,
        "ready": snapshot.ready,
        "commission_count": len(snapshot.commissions),
        "commissions": [asdict(row) for row in snapshot.commissions],
        "duplicate_conflicts": list(snapshot.duplicate_conflicts),
        "errors": list(snapshot.errors),
        "broker_connection_used": True,
        "order_sent": False,
        "live_order_sent": False,
        "live_trading": "PROHIBITED",
    }
    temporary = report_path.with_suffix(report_path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(report_path)


def main() -> int:
    snapshot = preview_ibkr_paper_commission_snapshot()
    persist_commission_snapshot(snapshot)
    print("===== IBKR PAPER COMMISSION EVIDENCE =====")
    print("CONNECTED        :", snapshot.connected)
    print("ENDPOINT PORT    :", snapshot.endpoint_port)
    print("READY            :", snapshot.ready)
    print("COMMISSION COUNT :", len(snapshot.commissions))
    print("CONFLICT COUNT   :", len(snapshot.duplicate_conflicts))
    print("ORDER SENT       : False")
    print("LIVE ORDER SENT  : False")
    print("LIVE TRADING     : PROHIBITED")
    print("REPORT           :", DEFAULT_REPORT_PATH)
    return 0 if snapshot.ready else 1


if __name__ == "__main__":
    raise SystemExit(main())

"""Explicit read-only IBKR Live account preflight.

This module exists only to prove that a future real-cash pilot is pointed at the
intended Live account/session before any Live order transport is used. It has no
order API calls, never enables Live Trading, and requires an exact operator
confirmation before it will even open a Live socket connection.

Default IBKR endpoints are tried in this order:
- IB Gateway Live: 4001
- TWS Live: 7496

The raw account identifier is never written to the report. A SHA-256 fingerprint
is stored instead so later pilot steps can pin the same account without exposing
the identifier in ordinary logs. Per-currency SettledCash values from the same
read-only account download are persisted so the pilot can require actual settled
cash in the instrument currency instead of relying on margin buying power.

IBKR can prefix per-currency account-value keys with ``$LEDGER-``. Both the
legacy ``SettledCash`` key and ``$LEDGER-SettledCash`` are accepted. If both
forms are observed for one currency with conflicting values, that currency is
omitted so the downstream cash gate fails closed rather than choosing one value.

Some IBKR accounts never emit a ``SettledCash``/``$LEDGER-SettledCash`` value at
all. IBKR's own ``AccountSummaryTags``/``Account Value Keys`` references state
that, for a Cash account, SettledCash is defined to equal TotalCashValue (and
that EquityWithLoanValue-S is itself defined as Settled Cash for a Cash
account). This module confirms the account is a Cash account from the
official, per-run, read-only ``TradingType-S`` tag (exact value ``STKCASH``,
captured from both ``updateAccountValue`` and ``accountSummary`` -- IBKR
documents it under the former but this account's API answers it under both --
so the check is not dependent on either single delivery path) before treating
the securities-segment settled-cash equivalent as settled cash for a currency
that has no distinct SettledCash value of its own. The equivalent is read only
from the securities-segment-scoped tags (``TotalCashValue-S`` and
``EquityWithLoanValue-S``), never the unsuffixed/blended totals, because
TradingType-S only certifies the securities segment and a universal account
could hold a separate commodities segment. The backfill is further restricted
to a run with zero open positions, so there is no in-flight trade whose
proceeds could appear in total cash before they are actually settled.

This is additive only: it never overrides a currency that already has a real
SettledCash/$LEDGER-SettledCash observation -- even one later excluded as
conflicting, which remains excluded rather than silently backfilled -- and it
is inert (behaves exactly as before) whenever TradingType-S is missing,
ambiguous, anything other than the exact confirmed Cash-account value, or the
account holds any open position.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
from threading import Thread

from ai_asset_platform.brokers.ibkr_account_snapshot import (
    IbkrBrokerPosition,
    _AccountSnapshotProbe,
    _base_currency,
    _summary_value,
)
from ai_asset_platform.brokers.ibkr_thread_runner import (
    run_ibapi_message_loop_safely,
)


CONFIRMATION_ENV = "AI_ASSET_LIVE_READONLY_CONFIRM"
CONFIRMATION_VALUE = "READ_LIVE_ACCOUNT_ONLY"
DEFAULT_REPORT_PATH = Path("results/ibkr_live_readonly_account_latest.json")
LIVE_GATEWAY_PORT = 4001
LIVE_TWS_PORT = 7496
REPORT_SCHEMA_VERSION = 3
_SETTLED_CASH_KEYS = {"SettledCash", "$LEDGER-SettledCash"}
# Securities-segment-scoped only (never the unsuffixed/blended totals): IBKR
# documents EquityWithLoanValue-S as literally "Settled Cash" for a Cash
# account, and TotalCashValue-S as that segment's cash. Cross-checking both
# keeps the same fail-closed-on-conflict behavior as the SettledCash keys
# above instead of trusting a single field.
_CASH_ACCOUNT_SETTLED_CASH_EQUIVALENT_KEYS = {"TotalCashValue-S", "EquityWithLoanValue-S"}
_SEGMENT_TRADING_TYPE_TAG = "TradingType-S"
_CASH_ACCOUNT_TRADING_TYPES = {"STKCASH"}


@dataclass(frozen=True)
class IbkrLiveReadOnlyAccountSnapshot:
    attempted: bool
    connected: bool
    endpoint_port: int | None
    account_fingerprint: str | None
    account_ready: bool
    base_currency: str | None
    net_liquidation: float | None
    available_funds: float | None
    gross_position_value: float | None
    total_cash_value: float | None
    segment_trading_type: str | None = None
    settled_cash_by_currency: dict[str, float] = field(default_factory=dict)
    positions: tuple[IbkrBrokerPosition, ...] = ()
    blocked_reason: str | None = None
    order_sent: bool = False
    live_order_sent: bool = False
    errors: tuple[str, ...] = field(default_factory=tuple)

    @property
    def ready(self) -> bool:
        return (
            self.attempted
            and self.connected
            and self.account_ready
            and self.account_fingerprint is not None
            and self.base_currency is not None
            and self.net_liquidation is not None
            and self.net_liquidation > 0
            and self.blocked_reason is None
            and not self.order_sent
            and not self.live_order_sent
        )


def _account_fingerprint(account_id: str) -> str:
    normalized = str(account_id).strip()
    if not normalized:
        raise ValueError("account_id is empty")
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _unambiguous_values_by_currency(
    account_values: dict[tuple[str, str], float], keys: set[str]
) -> tuple[dict[str, float], set[str]]:
    """Return (unambiguous finite per-currency values, currencies observed at all).

    If more than one key in ``keys`` reports a value for the same currency and
    those values disagree, that currency is left out of the returned mapping --
    but it is still included in the returned set, so a caller can tell "never
    observed" apart from "observed but invalid/conflicting" instead of silently
    treating both the same way.
    """
    observations: dict[str, list[float]] = {}
    for (key, currency), value in account_values.items():
        normalized_currency = str(currency or "").strip().upper()
        if key not in keys:
            continue
        if (
            len(normalized_currency) != 3
            or not normalized_currency.isalpha()
            or normalized_currency == "BASE"
        ):
            continue
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(parsed):
            continue
        observations.setdefault(normalized_currency, []).append(parsed)

    balances: dict[str, float] = {}
    for currency, values in observations.items():
        first = values[0]
        if all(math.isclose(item, first, rel_tol=1e-12, abs_tol=1e-9) for item in values[1:]):
            balances[currency] = first
    return balances, set(observations.keys())


def _currencies_observed_under_keys(probe: object, keys: set[str]) -> set[str]:
    """Return every currency with ANY observation under ``keys``, valid or not.

    Scans both the numeric ``account_values`` and the non-numeric
    ``account_text_values`` (an invalid/placeholder SettledCash value such as
    ``"-"`` or a literal ``"nan"`` string lands in the latter, never the
    former). This lets a caller treat "observed but invalid" the same as
    "observed but conflicting" -- never backfill-eligible -- instead of only
    catching currencies that happened to parse as a finite number.
    """
    observed: set[str] = set()
    for attr in ("account_values", "account_text_values"):
        source = getattr(probe, attr, None)
        if not isinstance(source, dict):
            continue
        for (key, currency), _value in source.items():
            if key not in keys:
                continue
            normalized_currency = str(currency or "").strip().upper()
            if (
                len(normalized_currency) == 3
                and normalized_currency.isalpha()
                and normalized_currency != "BASE"
            ):
                observed.add(normalized_currency)
    return observed


def _agreeing_values_present_for_every_key(
    account_values: dict[tuple[str, str], float], keys: set[str]
) -> dict[str, float]:
    """Return per-currency values observed under EVERY key in ``keys``, agreeing.

    Unlike ``_unambiguous_values_by_currency`` (where any one of several
    alternate names for the same field, such as ``SettledCash``/
    ``$LEDGER-SettledCash``, is sufficient), this requires an independent
    observation under each distinct key before accepting a currency -- a
    currency with only one of the keys present is excluded, not trivially
    accepted, because an ``all()`` over a single-element (or empty) remainder
    is vacuously true and would otherwise skip the cross-check entirely.
    """
    per_key_values: dict[str, dict[str, float]] = {}
    for (key, currency), value in account_values.items():
        if key not in keys:
            continue
        normalized_currency = str(currency or "").strip().upper()
        if (
            len(normalized_currency) != 3
            or not normalized_currency.isalpha()
            or normalized_currency == "BASE"
        ):
            continue
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(parsed):
            continue
        per_key_values.setdefault(normalized_currency, {})[key] = parsed

    balances: dict[str, float] = {}
    for currency, by_key in per_key_values.items():
        if set(by_key.keys()) != keys:
            continue
        values = list(by_key.values())
        first = values[0]
        if all(math.isclose(item, first, rel_tol=1e-12, abs_tol=1e-9) for item in values[1:]):
            balances[currency] = first
    return balances


def _segment_trading_type(probe: object) -> str | None:
    """Return the official, per-run ``TradingType-S`` value, if observed.

    This is the IBKR-documented securities-segment account type (for example
    ``STKCASH`` for a Cash account). IBKR documents this tag under
    ``updateAccountValue``, but this account's API has also answered it under
    ``accountSummary``; both delivery paths are checked so the result does not
    depend on either one alone. It is read fresh on every call; nothing is
    cached, hardcoded, or inferred from a prior manual confirmation. If the two
    paths disagree, the value is treated as unconfirmed (``None``) rather than
    picking one.
    """
    observed: set[str] = set()
    for attr in ("summary_text_values", "account_text_values"):
        text_values = getattr(probe, attr, None)
        if not isinstance(text_values, dict):
            continue
        value = text_values.get((_SEGMENT_TRADING_TYPE_TAG, ""))
        if value is None:
            continue
        normalized = str(value).strip().upper()
        if normalized:
            observed.add(normalized)
    if len(observed) == 1:
        return next(iter(observed))
    return None


def _settled_cash_by_currency(probe: _AccountSnapshotProbe) -> dict[str, float]:
    """Return unambiguous finite per-currency SettledCash evidence.

    Current IBKR sessions may emit per-currency keys either as ``SettledCash``
    or as ``$LEDGER-SettledCash`` depending on the TWS/API setting. If both key
    forms are present for the same currency, they must agree; otherwise that
    currency is excluded so the pilot cannot treat conflicting cash evidence as
    spendable settled cash.

    If the account's official, same-run ``TradingType-S`` tag confirms a Cash
    account (exact value ``STKCASH``) and the account currently holds zero open
    positions, a currency that was never observed under a SettledCash key at
    all -- not a conflicting observation, and not an invalid/non-numeric one
    either -- is additionally backfilled from the securities-segment-scoped
    ``TotalCashValue-S``/``EquityWithLoanValue-S`` equivalent -- IBKR's own
    documentation defines these as identical to settled cash for a Cash
    account, so this is not a fallback/substitute value. Both of those keys
    must be independently observed and agree; a currency with only one of
    them present is excluded, not trivially accepted. A currency with any
    real SettledCash observation, including one excluded for conflicting or
    for being non-numeric, is never touched by this backfill.
    """
    balances, _ = _unambiguous_values_by_currency(probe.account_values, _SETTLED_CASH_KEYS)
    observed_settled_currencies = _currencies_observed_under_keys(probe, _SETTLED_CASH_KEYS)
    has_open_positions = bool(getattr(probe, "portfolio", None))
    if (
        not has_open_positions
        and _segment_trading_type(probe) in _CASH_ACCOUNT_TRADING_TYPES
    ):
        equivalent = _agreeing_values_present_for_every_key(
            probe.account_values, _CASH_ACCOUNT_SETTLED_CASH_EQUIVALENT_KEYS
        )
        for currency, value in equivalent.items():
            if currency in observed_settled_currencies:
                continue
            balances.setdefault(currency, value)
    return dict(sorted(balances.items()))


def _blocked(reason: str) -> IbkrLiveReadOnlyAccountSnapshot:
    return IbkrLiveReadOnlyAccountSnapshot(
        attempted=False,
        connected=False,
        endpoint_port=None,
        account_fingerprint=None,
        account_ready=False,
        base_currency=None,
        net_liquidation=None,
        available_funds=None,
        gross_position_value=None,
        total_cash_value=None,
        settled_cash_by_currency={},
        positions=(),
        blocked_reason=reason,
        order_sent=False,
        live_order_sent=False,
        errors=(),
    )


def preview_ibkr_live_readonly_account_snapshot(
    *,
    timeout: float = 10.0,
    confirmation: str | None = None,
    endpoint_port: int | None = None,
) -> IbkrLiveReadOnlyAccountSnapshot:
    """Read one complete Live account snapshot without any order API request."""
    if timeout <= 0:
        raise ValueError("timeout must be positive")

    supplied = (
        str(confirmation).strip()
        if confirmation is not None
        else os.getenv(CONFIRMATION_ENV, "").strip()
    )
    if supplied != CONFIRMATION_VALUE:
        return _blocked("exact Live read-only confirmation is missing")

    if endpoint_port is not None and endpoint_port not in {LIVE_GATEWAY_PORT, LIVE_TWS_PORT}:
        raise ValueError("endpoint_port must identify an audited Live endpoint")

    ports = (endpoint_port,) if endpoint_port is not None else (LIVE_GATEWAY_PORT, LIVE_TWS_PORT)
    collected: list[str] = []
    for index, port in enumerate(ports, start=1):
        probe = _AccountSnapshotProbe()
        client_id = 370 + index
        try:
            try:
                probe.connect("127.0.0.1", port, client_id)
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
            if not probe.accounts_ready.wait(timeout) or len(probe.accounts) != 1:
                collected.extend(probe.errors)
                collected.append(
                    f"{port}: expected exactly one managed Live account; got {len(probe.accounts)}"
                )
                continue
            account_id = probe.accounts[0]

            probe.reqAccountUpdates(True, account_id)
            probe.reqAccountSummary(
                1991,
                "All",
                "NetLiquidation,AvailableFunds,GrossPositionValue,TotalCashValue,"
                + _SEGMENT_TRADING_TYPE_TAG
                + ","
                + ",".join(sorted(_CASH_ACCOUNT_SETTLED_CASH_EQUIVALENT_KEYS)),
            )
            download_complete = probe.download_ready.wait(timeout)
            summary_complete = probe.summary_ready.wait(timeout)
            try:
                probe.cancelAccountSummary(1991)
            except Exception:
                pass
            probe.reqAccountUpdates(False, account_id)

            if not download_complete or not summary_complete or probe.fatal_error:
                collected.extend(probe.errors)
                if not download_complete:
                    collected.append(
                        f"{port}: Live account download did not complete before timeout"
                    )
                if not summary_complete:
                    collected.append(
                        f"{port}: Live account summary did not complete before timeout"
                    )
                continue

            base_currency = _base_currency(probe)
            return IbkrLiveReadOnlyAccountSnapshot(
                attempted=True,
                connected=True,
                endpoint_port=port,
                account_fingerprint=_account_fingerprint(account_id),
                account_ready=bool(probe.account_ready),
                base_currency=base_currency,
                net_liquidation=_summary_value(probe, "NetLiquidation", base_currency),
                available_funds=_summary_value(probe, "AvailableFunds", base_currency),
                gross_position_value=_summary_value(
                    probe, "GrossPositionValue", base_currency
                ),
                total_cash_value=_summary_value(probe, "TotalCashValue", base_currency),
                segment_trading_type=_segment_trading_type(probe),
                settled_cash_by_currency=_settled_cash_by_currency(probe),
                positions=tuple(probe.portfolio),
                blocked_reason=None,
                order_sent=False,
                live_order_sent=False,
                errors=tuple(collected + probe.errors),
            )
        finally:
            if probe.isConnected():
                probe.disconnect()

    return IbkrLiveReadOnlyAccountSnapshot(
        attempted=True,
        connected=False,
        endpoint_port=None,
        account_fingerprint=None,
        account_ready=False,
        base_currency=None,
        net_liquidation=None,
        available_funds=None,
        gross_position_value=None,
        total_cash_value=None,
        settled_cash_by_currency={},
        positions=(),
        blocked_reason="no Live endpoint produced a complete read-only snapshot",
        order_sent=False,
        live_order_sent=False,
        errors=tuple(collected),
    )


def persist_live_readonly_account_snapshot(
    snapshot: IbkrLiveReadOnlyAccountSnapshot,
    *,
    report_path: Path = DEFAULT_REPORT_PATH,
) -> None:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": REPORT_SCHEMA_VERSION,
        **asdict(snapshot),
        "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "ready": snapshot.ready,
        "raw_account_id_persisted": False,
        "connection_mode": "LIVE_READ_ONLY",
        "broker_connection_used": snapshot.attempted,
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
    snapshot = preview_ibkr_live_readonly_account_snapshot()
    persist_live_readonly_account_snapshot(snapshot)
    print("===== IBKR LIVE READ-ONLY ACCOUNT PREFLIGHT =====")
    print("ATTEMPTED          :", snapshot.attempted)
    print("CONNECTED          :", snapshot.connected)
    print("ENDPOINT PORT      :", snapshot.endpoint_port)
    print("READY              :", snapshot.ready)
    print("ACCOUNT READY      :", snapshot.account_ready)
    print("BASE CURRENCY      :", snapshot.base_currency)
    print("SETTLED CASH CCYS  :", sorted(snapshot.settled_cash_by_currency))
    print("POSITION COUNT     :", len(snapshot.positions))
    print("RAW ACCOUNT ID     : NOT PERSISTED")
    print("BLOCKED REASON     :", snapshot.blocked_reason)
    print("ORDER SENT         : False")
    print("LIVE ORDER SENT    : False")
    print("REPORT             :", DEFAULT_REPORT_PATH)
    return 0 if snapshot.ready else 1


if __name__ == "__main__":
    raise SystemExit(main())

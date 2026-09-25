"""Read-only IBKR Live evidence via the Client Portal Gateway.

This module is a fallback evidence collector for environments where the classic
TWS/IB Gateway socket login cannot complete passkey authentication. It does not
authenticate the user, initialize or compete for a brokerage session, place or
preview an order, cancel/modify an order, or enable Live Trading.

The operator must first authenticate the Client Portal Gateway in a browser on
the same machine. This collector then uses only documented read-only GET
endpoints and fails closed unless the session proves it is Live (not Paper).

The current Live pilot preflight does NOT accept port 5000 yet. This module is
therefore evidence-only until a separate reviewed integration change is made.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
import ssl
import time
from typing import Callable
import urllib.error
import urllib.parse
import urllib.request

from ai_asset_platform.brokers.ibkr_live_all_open_orders import (
    REPORT_SCHEMA_VERSION as OPEN_ORDERS_SCHEMA_VERSION,
)
from ai_asset_platform.brokers.ibkr_live_fx_evidence import (
    REPORT_SCHEMA_VERSION as FX_SCHEMA_VERSION,
)
from ai_asset_platform.brokers.ibkr_live_readonly_account import (
    CONFIRMATION_VALUE,
    REPORT_SCHEMA_VERSION as ACCOUNT_SCHEMA_VERSION,
)


BASE_URL = "https://localhost:5000/v1/api"
ENDPOINT_PORT = 5000
TRANSPORT = "CLIENT_PORTAL_GATEWAY"
CONNECTION_MODE = "LIVE_READ_ONLY"

_TERMINAL_ORDER_STATUSES = {"filled", "cancelled"}


class ClientPortalReadOnlyError(RuntimeError):
    """Sanitized failure from the local read-only Client Portal collector."""


@dataclass(frozen=True)
class ClientPortalLiveEvidenceBundle:
    ready: bool
    checked_at: str
    blockers: tuple[str, ...]
    account_report: dict | None
    open_orders_report: dict | None
    fx_report: dict | None
    broker_connection_used: bool
    order_sent: bool = False
    cancel_sent: bool = False
    live_order_sent: bool = False


def _fingerprint(account_id: str) -> str:
    value = str(account_id or "").strip()
    if not value:
        raise ClientPortalReadOnlyError("Live account identity is empty")
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _finite(value: object) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _unwrap(payload: object) -> object:
    if isinstance(payload, dict):
        success = payload.get("success")
        if isinstance(success, dict) and "value" in success:
            return success["value"]
    return payload


def _localhost_context() -> ssl.SSLContext:
    # IBKR documents that the local CPGW ships without a signed localhost
    # certificate. TLS verification is disabled ONLY for the fixed localhost
    # base URL above; the destination is not user-configurable.
    return ssl._create_unverified_context()  # noqa: SLF001


def _get_json(
    path: str,
    *,
    params: dict[str, str] | None = None,
    timeout: float = 10.0,
) -> object:
    if not path.startswith("/") or "://" in path:
        raise ClientPortalReadOnlyError("invalid local Client Portal path")
    query = urllib.parse.urlencode(params or {})
    url = f"{BASE_URL}{path}" + (f"?{query}" if query else "")
    request = urllib.request.Request(
        url,
        headers={"Accept": "application/json", "User-Agent": "ai-asset-live-readonly"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(
            request,
            timeout=timeout,
            context=_localhost_context(),
        ) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise ClientPortalReadOnlyError(
            f"Client Portal read-only request failed with HTTP {exc.code}"
        ) from None
    except (urllib.error.URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError):
        raise ClientPortalReadOnlyError("Client Portal read-only request failed") from None


def _session_is_live(session: object) -> bool:
    session = _unwrap(session)
    if not isinstance(session, dict):
        return False
    result = session.get("RESULT", session.get("result"))
    login_type = session.get("LOGIN_TYPE", session.get("loginType"))
    return result is True and type(login_type) is int and login_type == 1


def _settled_cash(summary: dict) -> dict[str, float]:
    rows = summary.get("cashBalances")
    if not isinstance(rows, list):
        return {}
    result: dict[str, float] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        currency = str(row.get("currency") or "").strip().upper()
        value = _finite(row.get("settledCash"))
        if len(currency) != 3 or not currency.isalpha() or value is None:
            continue
        if currency in result and not math.isclose(
            result[currency], value, rel_tol=1e-12, abs_tol=1e-9
        ):
            result.pop(currency, None)
            continue
        result[currency] = value
    return dict(sorted(result.items()))


def _order_evidence(row: dict) -> dict:
    order_id = row.get("orderId", row.get("order_id"))
    try:
        order_id = int(order_id)
    except (TypeError, ValueError):
        order_id = -1
    quantity = _finite(row.get("totalSize", row.get("size")))
    return {
        "order_id": order_id,
        "symbol": str(row.get("ticker", row.get("symbol", "")) or "").strip().upper(),
        "local_symbol": str(row.get("description1", "") or "").strip().upper(),
        "sec_type": str(row.get("secType", row.get("sec_type", "")) or "").strip().upper(),
        "currency": str(row.get("cashCcy", row.get("currency", "")) or "").strip().upper(),
        "exchange": str(
            row.get("listingExchange", row.get("exchange", "")) or ""
        ).strip().upper(),
        "action": str(row.get("side", "") or "").strip().upper(),
        "quantity": quantity if quantity is not None else 0.0,
        "order_type": str(
            row.get("orderType", row.get("order_type", "")) or ""
        ).strip().upper(),
        "status": str(
            row.get("status", row.get("order_status", "")) or ""
        ).strip(),
        "client_id": None,
        "perm_id": None,
    }


def collect_client_portal_live_readonly_evidence(
    *,
    confirmation: str,
    base_currency: str = "USD",
    quote_currency: str = "JPY",
    timeout: float = 10.0,
    request_json: Callable[..., object] = _get_json,
    sleep_fn: Callable[[float], None] = time.sleep,
    now: datetime | None = None,
) -> ClientPortalLiveEvidenceBundle:
    """Collect Live account/open-order/FX evidence using read-only GET calls only."""
    checked = now if now is not None else datetime.now(timezone.utc)
    if checked.tzinfo is None or checked.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    checked_at = checked.astimezone(timezone.utc).isoformat(timespec="seconds")

    if str(confirmation or "").strip() != CONFIRMATION_VALUE:
        return ClientPortalLiveEvidenceBundle(
            ready=False,
            checked_at=checked_at,
            blockers=("exact Live read-only confirmation is missing",),
            account_report=None,
            open_orders_report=None,
            fx_report=None,
            broker_connection_used=False,
        )

    base = str(base_currency or "").strip().upper()
    quote = str(quote_currency or "").strip().upper()
    if (
        len(base) != 3
        or len(quote) != 3
        or not base.isalpha()
        or not quote.isalpha()
    ):
        raise ValueError("base/quote must be 3-letter currency codes")

    try:
        session = request_json("/sso/validate", timeout=timeout)
        if not _session_is_live(session):
            raise ClientPortalReadOnlyError(
                "Client Portal session is not a verified Live SSO session"
            )

        brokerage = _unwrap(request_json("/iserver/accounts", timeout=timeout))
        if not isinstance(brokerage, dict) or brokerage.get("isPaper") is not False:
            raise ClientPortalReadOnlyError(
                "Client Portal brokerage session is not verified as Live"
            )
        accounts = brokerage.get("accounts")
        if (
            not isinstance(accounts, list)
            or len(accounts) != 1
            or not isinstance(accounts[0], str)
            or not accounts[0].strip()
        ):
            raise ClientPortalReadOnlyError(
                "expected exactly one accessible Live brokerage account"
            )
        account_id = accounts[0].strip()
        selected = brokerage.get("selectedAccount")
        if selected not in (None, "") and str(selected).strip() != account_id:
            raise ClientPortalReadOnlyError(
                "selected Live account does not match the only accessible account"
            )
        account_fingerprint = _fingerprint(account_id)

        portfolio_accounts = _unwrap(
            request_json("/portfolio/accounts", timeout=timeout)
        )
        if not isinstance(portfolio_accounts, list):
            raise ClientPortalReadOnlyError("portfolio account metadata is unavailable")
        matching = [
            row
            for row in portfolio_accounts
            if isinstance(row, dict)
            and str(row.get("accountId", row.get("id", "")) or "").strip() == account_id
        ]
        if len(matching) != 1:
            raise ClientPortalReadOnlyError(
                "portfolio account identity does not match the Live brokerage account"
            )
        account_currency = str(matching[0].get("currency") or "").strip().upper()
        if len(account_currency) != 3 or not account_currency.isalpha():
            raise ClientPortalReadOnlyError("Live account base currency is unavailable")

        encoded_account = urllib.parse.quote(account_id, safe="")
        summary = _unwrap(
            request_json(
                f"/iserver/account/{encoded_account}/summary",
                timeout=timeout,
            )
        )
        if not isinstance(summary, dict):
            raise ClientPortalReadOnlyError("Live account summary is unavailable")

        positions = _unwrap(
            request_json(
                f"/portfolio2/{encoded_account}/positions",
                timeout=timeout,
            )
        )
        if not isinstance(positions, list):
            raise ClientPortalReadOnlyError("Live positions snapshot is unavailable")

        net_liquidation = _finite(summary.get("netLiquidationValue"))
        available_funds = _finite(summary.get("availableFunds"))
        gross_position_value = _finite(summary.get("securitiesGVP"))
        total_cash_value = _finite(summary.get("totalCashValue"))
        settled = _settled_cash(summary)
        account_ready = net_liquidation is not None and net_liquidation > 0

        account_report = {
            "schema_version": ACCOUNT_SCHEMA_VERSION,
            "checked_at": checked_at,
            "ready": bool(account_ready),
            "attempted": True,
            "connected": True,
            "endpoint_port": ENDPOINT_PORT,
            "transport": TRANSPORT,
            "session_live_verified": True,
            "account_fingerprint": account_fingerprint,
            "account_ready": bool(account_ready),
            "base_currency": account_currency,
            "net_liquidation": net_liquidation,
            "available_funds": available_funds,
            "gross_position_value": gross_position_value,
            "total_cash_value": total_cash_value,
            "settled_cash_by_currency": settled,
            "positions": positions,
            "raw_account_id_persisted": False,
            "connection_mode": CONNECTION_MODE,
            "broker_connection_used": True,
            "order_sent": False,
            "live_order_sent": False,
            "blocked_reason": None if account_ready else "Live account summary is incomplete",
            "errors": [],
        }

        # IBKR documents a 1 request / 5 sec pacing limit for this endpoint.
        # The force=true call clears the order cache; its response is discarded,
        # then a paced follow-up obtains the current-session snapshot.
        request_json(
            "/iserver/account/orders",
            params={"force": "true"},
            timeout=timeout,
        )
        sleep_fn(5.1)
        orders_payload = _unwrap(
            request_json("/iserver/account/orders", timeout=timeout)
        )
        if not isinstance(orders_payload, dict):
            raise ClientPortalReadOnlyError("Live order snapshot is unavailable")
        rows = orders_payload.get("orders", [])
        if not isinstance(rows, list):
            raise ClientPortalReadOnlyError("Live order rows are malformed")

        active_orders: list[dict] = []
        for row in rows:
            if not isinstance(row, dict):
                raise ClientPortalReadOnlyError("Live order row is malformed")
            status = str(
                row.get("status", row.get("order_status", "")) or ""
            ).strip().lower()
            if status in _TERMINAL_ORDER_STATUSES:
                continue
            row_account = str(
                row.get("acct", row.get("account", "")) or ""
            ).strip()
            if not row_account or row_account != account_id:
                raise ClientPortalReadOnlyError(
                    "an active Live order is not bound to the verified account"
                )
            active_orders.append(_order_evidence(row))

        open_orders_report = {
            "schema_version": OPEN_ORDERS_SCHEMA_VERSION,
            "checked_at": checked_at,
            "attempted": True,
            "connected": True,
            "ready": True,
            "endpoint_port": ENDPOINT_PORT,
            "transport": TRANSPORT,
            "session_live_verified": True,
            "account_fingerprint": account_fingerprint,
            "open_order_count": len(active_orders),
            "orders": active_orders,
            "raw_account_id_persisted": False,
            "connection_mode": CONNECTION_MODE,
            "broker_connection_used": True,
            "blocked_reason": None,
            "errors": [],
            "order_sent": False,
            "cancel_sent": False,
            "live_order_sent": False,
        }

        fx_payload = _unwrap(
            request_json(
                "/iserver/exchangerate",
                params={"source": base, "target": quote},
                timeout=timeout,
            )
        )
        if not isinstance(fx_payload, dict):
            raise ClientPortalReadOnlyError("Live FX evidence is unavailable")
        rate = _finite(fx_payload.get("rate"))
        fx_ready = rate is not None and rate > 0
        fx_report = {
            "schema_version": FX_SCHEMA_VERSION,
            "checked_at": checked_at,
            "ready": bool(fx_ready),
            "connected": True,
            "endpoint_port": ENDPOINT_PORT,
            "transport": TRANSPORT,
            "session_live_verified": True,
            "base_currency": base,
            "quote_currency": quote,
            "exchange": "IBKR_WEB_API",
            "bid": None,
            "ask": None,
            "rate": rate,
            "source": "CLIENT_PORTAL_EXCHANGE_RATE",
            "connection_mode": CONNECTION_MODE,
            "broker_connection_used": True,
            "order_sent": False,
            "live_order_sent": False,
            "errors": [] if fx_ready else ["Live FX rate is unavailable"],
        }

        blockers: list[str] = []
        if not account_report["ready"]:
            blockers.append("Live account evidence is incomplete")
        if not fx_report["ready"]:
            blockers.append("Live FX evidence is incomplete")

        return ClientPortalLiveEvidenceBundle(
            ready=not blockers,
            checked_at=checked_at,
            blockers=tuple(blockers),
            account_report=account_report,
            open_orders_report=open_orders_report,
            fx_report=fx_report,
            broker_connection_used=True,
            order_sent=False,
            cancel_sent=False,
            live_order_sent=False,
        )
    except ClientPortalReadOnlyError as exc:
        return ClientPortalLiveEvidenceBundle(
            ready=False,
            checked_at=checked_at,
            blockers=(str(exc),),
            account_report=None,
            open_orders_report=None,
            fx_report=None,
            broker_connection_used=True,
            order_sent=False,
            cancel_sent=False,
            live_order_sent=False,
        )

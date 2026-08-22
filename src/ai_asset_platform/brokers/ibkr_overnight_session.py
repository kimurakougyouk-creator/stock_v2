"""Read-only broker session gate for the verified SPY Overnight Paper pilot.

The gate asks IBKR for the directed OVERNIGHT ContractDetails tradingHours and
for IBKR server time. It does not infer holidays from a local weekday calendar
and it never creates/transmits an order. A real Paper E2E may proceed only when
the broker-reported current time falls inside one of the returned trading-hour
intervals.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from threading import Event, Thread
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ibapi.client import EClient
from ibapi.contract import Contract, ContractDetails
from ibapi.wrapper import EWrapper

from ai_asset_platform.brokers.ibkr_config import create_ibkr_paper_config
from ai_asset_platform.brokers.ibkr_contracts import build_ibkr_contract_spec, to_ibapi_contract
from ai_asset_platform.brokers.instruments import InstrumentSpec
from ai_asset_platform.core.asset_classes import AssetClass


@dataclass(frozen=True)
class IbkrOvernightSessionResult:
    connected: bool
    contract_resolved: bool
    symbol: str
    destination: str
    primary_exchange: str
    server_time_utc: datetime | None
    timezone_id: str | None
    trading_hours: str | None
    liquid_hours: str | None
    open_now: bool
    order_sent: bool = False
    errors: tuple[str, ...] = field(default_factory=tuple)

    @property
    def ready(self) -> bool:
        return (
            self.connected
            and self.contract_resolved
            and self.server_time_utc is not None
            and bool(self.timezone_id)
            and bool(self.trading_hours)
            and self.open_now
            and not self.order_sent
        )


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


def _parse_stamp(value: str, *, default_date: str, zone: ZoneInfo) -> datetime:
    raw = value.strip()
    if len(raw) == 4 and raw.isdigit():
        raw = default_date + raw
    if len(raw) != 12 or not raw.isdigit():
        raise ValueError(f"invalid IBKR trading-hours timestamp: {value}")
    return datetime.strptime(raw, "%Y%m%d%H%M").replace(tzinfo=zone)


def parse_ibkr_trading_intervals(raw: str, timezone_id: str) -> tuple[tuple[datetime, datetime], ...]:
    """Parse standard ContractDetails tradingHours segments fail-closed."""
    try:
        zone = ZoneInfo(str(timezone_id).strip())
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError("IBKR ContractDetails timezone_id is invalid") from exc
    intervals: list[tuple[datetime, datetime]] = []
    for segment in str(raw or "").split(";"):
        segment = segment.strip()
        if not segment:
            continue
        if ":" not in segment:
            raise ValueError(f"invalid IBKR trading-hours segment: {segment}")
        date_part, payload = segment.split(":", 1)
        if payload.strip().upper() == "CLOSED":
            continue
        for window in payload.split(","):
            window = window.strip()
            if not window:
                continue
            if "-" not in window:
                raise ValueError(f"invalid IBKR trading-hours window: {window}")
            start_raw, end_raw = window.split("-", 1)
            start = _parse_stamp(start_raw, default_date=date_part, zone=zone)
            end = _parse_stamp(end_raw, default_date=date_part, zone=zone)
            if end <= start:
                raise ValueError("IBKR trading-hours interval is not increasing")
            intervals.append((start, end))
    return tuple(intervals)


def is_broker_session_open(*, server_time_utc: datetime, trading_hours: str, timezone_id: str) -> bool:
    if server_time_utc.tzinfo is None:
        raise ValueError("server_time_utc must be timezone-aware")
    intervals = parse_ibkr_trading_intervals(trading_hours, timezone_id)
    local = server_time_utc.astimezone(ZoneInfo(timezone_id))
    return any(start <= local < end for start, end in intervals)


class _SessionProbe(EWrapper, EClient):
    def __init__(self) -> None:
        EWrapper.__init__(self)
        EClient.__init__(self, self)
        self.connected_ready = Event()
        self.time_ready = Event()
        self.details_ready = Event()
        self.server_time_utc: datetime | None = None
        self.details: list[ContractDetails] = []
        self.errors: list[str] = []
        self.fatal_error: str | None = None

    def nextValidId(self, orderId: int) -> None:  # noqa: N802
        self.connected_ready.set()

    def currentTime(self, time: int) -> None:  # noqa: N802
        try:
            self.server_time_utc = datetime.fromtimestamp(int(time), tz=timezone.utc)
        finally:
            self.time_ready.set()

    def contractDetails(self, reqId: int, contractDetails: ContractDetails) -> None:  # noqa: N802
        self.details.append(contractDetails)

    def contractDetailsEnd(self, reqId: int) -> None:  # noqa: N802
        self.details_ready.set()

    def error(self, reqId, *args):
        parsed = _parse_error(args)
        if parsed is None:
            return
        code, text = parsed
        message = f"{code}: {text}"
        self.errors.append(message)
        if code in {200, 326, 502, 503, 504, 1100}:
            self.fatal_error = message
            self.connected_ready.set()
            self.time_ready.set()
            self.details_ready.set()


def _overnight_contract(symbol: str = "SPY", primary_exchange: str = "ARCA") -> Contract:
    instrument = InstrumentSpec(
        symbol.strip().upper(),
        AssetClass.ETF,
        exchange="OVERNIGHT",
        currency="USD",
        primary_exchange=primary_exchange.strip().upper(),
    )
    return to_ibapi_contract(build_ibkr_contract_spec(instrument))


def preview_ibkr_paper_overnight_session(
    *,
    symbol: str = "SPY",
    primary_exchange: str = "ARCA",
    timeout: float = 8.0,
) -> IbkrOvernightSessionResult:
    """Read current broker time + directed contract trading hours from Paper."""
    errors: list[str] = []
    normalized = symbol.strip().upper()
    primary = primary_exchange.strip().upper()
    contract = _overnight_contract(normalized, primary)
    for use_gateway in (True, False):
        cfg = create_ibkr_paper_config(use_gateway=use_gateway)
        probe = _SessionProbe()
        try:
            try:
                probe.connect(cfg.host, cfg.port, cfg.client_id + 271)
            except OSError as exc:
                errors.append(f"{cfg.port}: {exc}")
                continue
            Thread(target=probe.run, daemon=True).start()
            if not probe.connected_ready.wait(timeout) or probe.fatal_error:
                errors.extend(probe.errors)
                continue
            probe.reqCurrentTime()
            probe.reqContractDetails(771, contract)
            probe.time_ready.wait(timeout)
            probe.details_ready.wait(timeout)
            if probe.fatal_error:
                errors.extend(probe.errors)
                continue
            if probe.server_time_utc is None or len(probe.details) != 1:
                errors.extend(probe.errors)
                errors.append(
                    f"{cfg.port}: expected one directed OVERNIGHT contract and broker time; "
                    f"details={len(probe.details)} time={probe.server_time_utc is not None}"
                )
                continue
            details = probe.details[0]
            timezone_id = str(getattr(details, "timeZoneId", "") or "").strip() or None
            trading_hours = str(getattr(details, "tradingHours", "") or "").strip() or None
            liquid_hours = str(getattr(details, "liquidHours", "") or "").strip() or None
            open_now = False
            if timezone_id and trading_hours:
                try:
                    open_now = is_broker_session_open(
                        server_time_utc=probe.server_time_utc,
                        trading_hours=trading_hours,
                        timezone_id=timezone_id,
                    )
                except ValueError as exc:
                    errors.append(f"{cfg.port}: {exc}")
            return IbkrOvernightSessionResult(
                connected=True,
                contract_resolved=True,
                symbol=normalized,
                destination="OVERNIGHT",
                primary_exchange=primary,
                server_time_utc=probe.server_time_utc,
                timezone_id=timezone_id,
                trading_hours=trading_hours,
                liquid_hours=liquid_hours,
                open_now=open_now,
                order_sent=False,
                errors=tuple(errors + probe.errors),
            )
        finally:
            if probe.isConnected():
                probe.disconnect()
    return IbkrOvernightSessionResult(
        connected=False,
        contract_resolved=False,
        symbol=normalized,
        destination="OVERNIGHT",
        primary_exchange=primary,
        server_time_utc=None,
        timezone_id=None,
        trading_hours=None,
        liquid_hours=None,
        open_now=False,
        order_sent=False,
        errors=tuple(errors),
    )

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from ai_asset_platform.brokers.base import BrokerAdapter
from ai_asset_platform.brokers.ibkr_config import (
    IbkrConnectionConfig,
    create_ibkr_paper_config,
)
from ai_asset_platform.brokers.ibkr_fill_runtime import IbkrFillRuntime
from ai_asset_platform.brokers.ibkr_order_events import (
    IbkrOrderState,
    normalize_ibkr_order_state,
)
from ai_asset_platform.brokers.ibkr_paper_transmitter import transmit_ibkr_paper_order
from ai_asset_platform.brokers.ibkr_session import (
    IbkrConnectionDiagnostics,
    IbkrPaperSession,
    open_ibkr_paper_session,
)
from ai_asset_platform.brokers.instruments import InstrumentSpec
from ai_asset_platform.brokers.orders import FillResult, OrderRequest, OrderResult, OrderStatus

_TERMINAL_ORDER_STATES = frozenset(
    {
        IbkrOrderState.FILLED,
        IbkrOrderState.CANCELLED,
        IbkrOrderState.API_CANCELLED,
        IbkrOrderState.INACTIVE,
    }
)

DEFAULT_ASYNC_ORDER_TIMEOUT_SECONDS = 30.0
DEFAULT_ASYNC_ORDER_POLL_INTERVAL_SECONDS = 0.5
DEFAULT_INTENT_LOCK_DIR = "data/ibkr_order_intent_locks"
_INTENT_ID_SAFE_PATTERN = re.compile(r"[^A-Za-z0-9_.-]+")


def _sanitize_intent_id(order_intent_id: str) -> str:
    return _INTENT_ID_SAFE_PATTERN.sub("_", order_intent_id)


def _acquire_intent_lock(lock_path: Path) -> bool:
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return False
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(json.dumps({"pid": os.getpid(), "acquired_at": time.time()}, ensure_ascii=False))
    return True


def _release_intent_lock(lock_path: Path) -> None:
    lock_path.unlink(missing_ok=True)


@dataclass(frozen=True)
class IbkrAsyncOrderResult:
    order_intent_id: str
    status: str
    sent: bool
    order_id: int | None
    reached_terminal: bool
    timed_out: bool
    last_known_status: str | None
    filled_quantity: float
    avg_fill_price: float | None
    message: str
    diagnostics: IbkrConnectionDiagnostics | None = None
    errors: list[dict] = field(default_factory=list)
    open_orders: dict[int, dict] = field(default_factory=dict)
    executions: list[dict] = field(default_factory=list)


class IbkrBrokerAdapter(BrokerAdapter):
    """IBKR Paper Trading adapter. Sending is disabled by default; Live is forbidden."""

    def __init__(
        self,
        config: IbkrConnectionConfig | None = None,
        *,
        enable_paper_order_transmission: bool = False,
        fill_state_path: str | Path = "data/ibkr_fill_state.json",
        on_fill: Callable[[FillResult], None] | None = None,
    ) -> None:
        self.config = config or create_ibkr_paper_config()
        self._session: IbkrPaperSession | None = None
        self._enable_paper_order_transmission = enable_paper_order_transmission
        self._fill_runtime = IbkrFillRuntime(fill_state_path, on_fill=on_fill)
        self.last_failed_diagnostics: IbkrConnectionDiagnostics | None = None
        self.last_failed_errors: list[dict] = []
        self._attempted_intent_ids: set[str] = set()

    @property
    def name(self) -> str:
        return "IBKR"

    def connect(self, *, connect_timeout: float | None = None) -> bool:
        self.config.validate()
        if self.is_connected():
            return True

        def _capture_failed_diagnostics(client, thread) -> None:
            exc = client.message_loop_exception
            self.last_failed_diagnostics = IbkrConnectionDiagnostics(
                server_version=client.server_version,
                next_valid_id=client.next_order_id,
                is_connected=client.isConnected(),
                message_loop_alive=thread.is_alive(),
                message_loop_exception=repr(exc) if exc is not None else None,
            )
            self.last_failed_errors = list(client.errors)

        kwargs = {} if connect_timeout is None else {"timeout": connect_timeout}
        self._session = open_ibkr_paper_session(
            self.config,
            order_status_handler=self._fill_runtime.process_order_status,
            exec_details_handler=self._fill_runtime.process_execution,
            on_failed_connect=_capture_failed_diagnostics,
            **kwargs,
        )
        return self.is_connected()

    def is_connected(self) -> bool:
        return self._session is not None and self._session.connected

    def disconnect(self) -> None:
        if self._session is not None:
            self._session.disconnect()
        self._session = None

    def place_order(self, order: OrderRequest, *, instrument: InstrumentSpec | None = None) -> OrderResult:
        if not self.is_connected() or self._session is None:
            return OrderResult("IBKR-NOT-CONNECTED", OrderStatus.REJECTED, "IBKRへ接続されていないため注文しません。")
        result = transmit_ibkr_paper_order(
            order,
            self.config,
            client=self._session.client,
            next_order_id=self._session.next_order_id,
            enable_transmission=self._enable_paper_order_transmission,
            instrument=instrument,
        )
        if not result.sent:
            return OrderResult(str(result.order_id) if result.order_id is not None else "IBKR-PAPER-NOT-SENT", OrderStatus.REJECTED, result.message)
        if result.order_id is None:
            return OrderResult("IBKR-PAPER-MISSING-ORDER-ID", OrderStatus.REJECTED, "IBKR Paper注文IDを確認できませんでした。")
        self._fill_runtime.register_order(result.order_id, order)
        self._session.next_order_id += 1
        return OrderResult(str(result.order_id), OrderStatus.ACCEPTED, result.message)

    def processed_filled(self, order_id: int) -> float:
        return self._fill_runtime.processed_filled(order_id)

    def place_order_and_await_fill(
        self,
        order: OrderRequest,
        *,
        order_intent_id: str,
        instrument: InstrumentSpec | None = None,
        timeout_seconds: float = DEFAULT_ASYNC_ORDER_TIMEOUT_SECONDS,
        poll_interval_seconds: float = DEFAULT_ASYNC_ORDER_POLL_INTERVAL_SECONDS,
        intent_lock_dir: str | Path = DEFAULT_INTENT_LOCK_DIR,
        now_fn: Callable[[], float] = time.monotonic,
        sleep_fn: Callable[[float], None] = time.sleep,
    ) -> IbkrAsyncOrderResult:
        if not order_intent_id.strip():
            raise ValueError("order_intent_idは必須です。")
        if order_intent_id in self._attempted_intent_ids:
            return IbkrAsyncOrderResult(order_intent_id, "DUPLICATE_BLOCKED", False, None, False, False, None, 0.0, None, "このorder_intent_idはこのインスタンスで既に試行済みのため、再送信をブロックしました。")
        self._attempted_intent_ids.add(order_intent_id)

        lock_path = Path(intent_lock_dir) / f"{_sanitize_intent_id(order_intent_id)}.lock"
        if not _acquire_intent_lock(lock_path):
            return IbkrAsyncOrderResult(order_intent_id, "DUPLICATE_BLOCKED", False, None, False, False, None, 0.0, None, f"このorder_intent_idは別プロセス/以前の実行で既に試行済みです(ロック: {lock_path})。重複送信をブロックしました。")

        result = self.place_order(order, instrument=instrument)
        if result.status is not OrderStatus.ACCEPTED:
            _release_intent_lock(lock_path)
            diagnostics = self._session.diagnostics() if self._session is not None else None
            errors = list(self._session.client.errors) if self._session else []
            open_orders = dict(self._session.client.open_orders) if self._session else {}
            executions = list(self._session.client.executions) if self._session else []
            return IbkrAsyncOrderResult(order_intent_id, "NOT_SENT", False, None, False, False, None, 0.0, None, result.message, diagnostics, errors, open_orders, executions)

        order_id = int(result.order_id)
        client = self._session.client  # type: ignore[union-attr]
        deadline = now_fn() + timeout_seconds
        reached_terminal = False
        while now_fn() < deadline:
            open_order = client.open_orders.get(order_id)
            status_text = open_order.get("status") if open_order else None
            filled_quantity = self.processed_filled(order_id)
            if status_text is not None and normalize_ibkr_order_state(status_text) in _TERMINAL_ORDER_STATES:
                reached_terminal = True
                break
            if filled_quantity >= order.quantity:
                reached_terminal = True
                break
            sleep_fn(poll_interval_seconds)

        filled_quantity = self.processed_filled(order_id)
        open_order = client.open_orders.get(order_id)
        last_known_status = open_order.get("status") if open_order else None
        order_executions = [e for e in client.executions if e["order_id"] == order_id]
        avg_fill_price: float | None = None
        if order_executions:
            total_shares = sum(e["shares"] for e in order_executions)
            if total_shares > 0:
                avg_fill_price = sum(e["shares"] * e["price"] for e in order_executions) / total_shares

        diagnostics = self._session.diagnostics()
        errors = list(client.errors)
        open_orders = dict(client.open_orders)
        return IbkrAsyncOrderResult(
            order_intent_id=order_intent_id,
            status="TERMINAL" if reached_terminal else "TIMEOUT",
            sent=True,
            order_id=order_id,
            reached_terminal=reached_terminal,
            timed_out=not reached_terminal,
            last_known_status=last_known_status,
            filled_quantity=filled_quantity,
            avg_fill_price=avg_fill_price,
            message="終端状態に到達しました。" if reached_terminal else f"{timeout_seconds}秒以内に終端状態へ到達しませんでした(未確定)。自動再送信はしません。",
            diagnostics=diagnostics,
            errors=errors,
            open_orders=open_orders,
            executions=order_executions,
        )

    def fill_order(self, order: OrderRequest, price: float) -> FillResult:
        raise RuntimeError("IBKRの手動実約定処理は有効化されていません。")

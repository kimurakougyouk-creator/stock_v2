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
from ai_asset_platform.brokers.ibkr_paper_transmitter import (
    transmit_ibkr_paper_order,
)
from ai_asset_platform.brokers.ibkr_session import (
    IbkrConnectionDiagnostics,
    IbkrPaperSession,
    open_ibkr_paper_session,
)
from ai_asset_platform.brokers.orders import (
    FillResult,
    OrderRequest,
    OrderResult,
    OrderStatus,
)

# place_order_and_await_fill()が終端とみなす注文状態。
# ibkr_first_paper_test_confirmation.pyのTERMINAL_ORDER_STATESと同じ定義。
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
    """order_intent_id単位の排他ロックを取得する。

    os.O_CREAT|os.O_EXCLのアトミック性により、プロセスを跨いでも
    同一order_intent_idに対しては1者しか取得できないことを保証する。
    """
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return False

    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(
            json.dumps(
                {"pid": os.getpid(), "acquired_at": time.time()},
                ensure_ascii=False,
            )
        )
    return True


def _release_intent_lock(lock_path: Path) -> None:
    lock_path.unlink(missing_ok=True)


@dataclass(frozen=True)
class IbkrAsyncOrderResult:
    """place_order_and_await_fill()の結果。約定/未約定を推測しない。"""

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
    """IBKR Paper Trading用Broker Adapter。

    接続、Paper注文、orderStatus、差分約定、永続化を一か所に統合する。
    注文送信はデフォルトで無効。Live Tradingは許可しない。
    """

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
        self._fill_runtime = IbkrFillRuntime(
            fill_state_path,
            on_fill=on_fill,
        )
        # 直近の接続失敗時の観測データ(接続成功時は更新しない・古いまま残る)。
        self.last_failed_diagnostics: IbkrConnectionDiagnostics | None = None
        self.last_failed_errors: list[dict] = []
        # place_order_and_await_fill()の重複送信防止用。
        # プロセス内では、このインスタンスが一度試行したorder_intent_idは
        # 結果に関わらず二度と試行しない(生涯1回ロックとは異なり、
        # intent_idごとに独立している)。
        self._attempted_intent_ids: set[str] = set()

    @property
    def name(self) -> str:
        return "IBKR"

    def connect(self, *, connect_timeout: float | None = None) -> bool:
        """IBKR Paperへ接続する。

        connect_timeoutを指定すると、nextValidId受信を待つ最大秒数だけを
        変更できる(既定値5.0秒は変更しない呼び出し側の挙動を維持するため)。
        接続に失敗した場合でも、その時点までに観測できたerrors/diagnosticsを
        last_failed_errors/last_failed_diagnosticsへ保存する。
        リトライや自動再接続は一切行わない(1回の接続試行のみ)。
        """
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

    def place_order(self, order: OrderRequest) -> OrderResult:
        if not self.is_connected() or self._session is None:
            return OrderResult(
                order_id="IBKR-NOT-CONNECTED",
                status=OrderStatus.REJECTED,
                message="IBKRへ接続されていないため注文しません。",
            )

        result = transmit_ibkr_paper_order(
            order,
            self.config,
            client=self._session.client,
            next_order_id=self._session.next_order_id,
            enable_transmission=self._enable_paper_order_transmission,
        )

        if not result.sent:
            return OrderResult(
                order_id=(
                    str(result.order_id)
                    if result.order_id is not None
                    else "IBKR-PAPER-NOT-SENT"
                ),
                status=OrderStatus.REJECTED,
                message=result.message,
            )

        if result.order_id is None:
            return OrderResult(
                order_id="IBKR-PAPER-MISSING-ORDER-ID",
                status=OrderStatus.REJECTED,
                message="IBKR Paper注文IDを確認できませんでした。",
            )

        self._fill_runtime.register_order(result.order_id, order)
        self._session.next_order_id += 1

        return OrderResult(
            order_id=str(result.order_id),
            status=OrderStatus.ACCEPTED,
            message=result.message,
        )

    def processed_filled(self, order_id: int) -> float:
        return self._fill_runtime.processed_filled(order_id)

    def place_order_and_await_fill(
        self,
        order: OrderRequest,
        *,
        order_intent_id: str,
        timeout_seconds: float = DEFAULT_ASYNC_ORDER_TIMEOUT_SECONDS,
        poll_interval_seconds: float = DEFAULT_ASYNC_ORDER_POLL_INTERVAL_SECONDS,
        intent_lock_dir: str | Path = DEFAULT_INTENT_LOCK_DIR,
        now_fn: Callable[[], float] = time.monotonic,
        sleep_fn: Callable[[float], None] = time.sleep,
    ) -> IbkrAsyncOrderResult:
        """
        IBKR Paperへ注文を送信し(最大1回)、終端状態に到達するかtimeout_seconds
        が経過するまで、既存の観測基盤(orderStatus/openOrder/execDetails/
        error/diagnostics)を使って監視する。

        新しい発注ロジックは持たない。既存のplace_order()を1回だけ呼ぶ
        だけであり、送信自体の安全条件(Paper固定・Live禁止・TIF=DAY等)は
        prepare_ibkr_paper_order()/transmit_ibkr_paper_order()にすべて委ねる。

        order_intent_idは呼び出し側が用意する、この注文意図を一意に表す
        キー(例: シグナルID)。同一order_intent_idに対する2回目以降の
        呼び出しは、結果に関わらず必ずDUPLICATE_BLOCKEDになる
        (プロセス内: インスタンスごとの集合、プロセス跨ぎ: ロックファイルの
        アトミックな排他作成)。first-paper-test専用の「生涯1回」ロックとは
        異なり、intent_idごとに独立しているため、別の正当な注文は妨げない。

        タイムアウトしても自動的な再送信は一切行わない。
        約定/未約定は観測できた事実のみで判定し、推測しない。
        """
        if not order_intent_id.strip():
            raise ValueError("order_intent_idは必須です。")

        if order_intent_id in self._attempted_intent_ids:
            return IbkrAsyncOrderResult(
                order_intent_id=order_intent_id,
                status="DUPLICATE_BLOCKED",
                sent=False,
                order_id=None,
                reached_terminal=False,
                timed_out=False,
                last_known_status=None,
                filled_quantity=0.0,
                avg_fill_price=None,
                message=(
                    "このorder_intent_idはこのインスタンスで既に試行済み"
                    "のため、再送信をブロックしました。"
                ),
            )
        self._attempted_intent_ids.add(order_intent_id)

        lock_path = (
            Path(intent_lock_dir) / f"{_sanitize_intent_id(order_intent_id)}.lock"
        )
        if not _acquire_intent_lock(lock_path):
            return IbkrAsyncOrderResult(
                order_intent_id=order_intent_id,
                status="DUPLICATE_BLOCKED",
                sent=False,
                order_id=None,
                reached_terminal=False,
                timed_out=False,
                last_known_status=None,
                filled_quantity=0.0,
                avg_fill_price=None,
                message=(
                    "このorder_intent_idは別プロセス/以前の実行で既に"
                    f"試行済みです(ロック: {lock_path})。重複送信を"
                    "ブロックしました。"
                ),
            )

        # ===== 送信はここで1回だけ =====
        result = self.place_order(order)

        if result.status is not OrderStatus.ACCEPTED:
            # 実際には送信されなかったことが確定したため、正当な再試行
            # (新しいインスタンス/プロセスから同じintent_idで)を妨げない
            # よう、ファイルロックだけは解放する。プロセス内の
            # _attempted_intent_idsはこのインスタンスでは解除しない。
            _release_intent_lock(lock_path)
            diagnostics = (
                self._session.diagnostics() if self._session is not None else None
            )
            errors = list(self._session.client.errors) if self._session else []
            open_orders = (
                dict(self._session.client.open_orders) if self._session else {}
            )
            executions = (
                list(self._session.client.executions) if self._session else []
            )
            return IbkrAsyncOrderResult(
                order_intent_id=order_intent_id,
                status="NOT_SENT",
                sent=False,
                order_id=None,
                reached_terminal=False,
                timed_out=False,
                last_known_status=None,
                filled_quantity=0.0,
                avg_fill_price=None,
                message=result.message,
                diagnostics=diagnostics,
                errors=errors,
                open_orders=open_orders,
                executions=executions,
            )

        # ここから先は送信成功(sent=True)確定。ロックは解放しない
        # (同じintent_idでの再試行は今後も常にDUPLICATE_BLOCKEDになる)。
        order_id = int(result.order_id)
        client = self._session.client  # type: ignore[union-attr]

        deadline = now_fn() + timeout_seconds
        reached_terminal = False

        while now_fn() < deadline:
            open_order = client.open_orders.get(order_id)
            status_text = open_order.get("status") if open_order else None
            filled_quantity = self.processed_filled(order_id)

            if (
                status_text is not None
                and normalize_ibkr_order_state(status_text) in _TERMINAL_ORDER_STATES
            ):
                reached_terminal = True
                break

            if filled_quantity >= order.quantity:
                reached_terminal = True
                break

            sleep_fn(poll_interval_seconds)

        filled_quantity = self.processed_filled(order_id)
        open_order = client.open_orders.get(order_id)
        last_known_status = open_order.get("status") if open_order else None

        order_executions = [
            e for e in client.executions if e["order_id"] == order_id
        ]
        avg_fill_price: float | None = None
        if order_executions:
            total_shares = sum(e["shares"] for e in order_executions)
            if total_shares > 0:
                avg_fill_price = (
                    sum(e["shares"] * e["price"] for e in order_executions)
                    / total_shares
                )

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
            message=(
                "終端状態に到達しました。"
                if reached_terminal
                else (
                    f"{timeout_seconds}秒以内に終端状態へ到達しませんでした"
                    "(未確定)。自動再送信はしません。"
                )
            ),
            diagnostics=diagnostics,
            errors=errors,
            open_orders=open_orders,
            executions=order_executions,
        )

    def fill_order(
        self,
        order: OrderRequest,
        price: float,
    ) -> FillResult:
        raise RuntimeError(
            "IBKRの手動実約定処理は有効化されていません。"
        )

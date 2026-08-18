from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from ibapi.execution import ExecutionFilter

from ai_asset_platform.brokers.ibkr import IbkrBrokerAdapter
from ai_asset_platform.brokers.ibkr_config import IbkrConnectionConfig
from ai_asset_platform.brokers.ibkr_first_paper_test import (
    DEFAULT_ACCOUNT_VERIFICATION_TIMEOUT_SECONDS,
    REQUIRED_CLIENT_ID,
    REQUIRED_HOST,
    REQUIRED_PORT,
    REQUIRED_QUANTITY,
    REQUIRED_SIDE,
    REQUIRED_SYMBOL,
    IbkrFirstPaperTestGateway,
    IbkrFirstPaperTestResult,
)
from ai_asset_platform.brokers.ibkr_order_events import (
    IbkrOrderState,
    normalize_ibkr_order_state,
)
from ai_asset_platform.brokers.orders import OrderRequest

TERMINAL_ORDER_STATES = frozenset(
    {
        IbkrOrderState.FILLED,
        IbkrOrderState.CANCELLED,
        IbkrOrderState.API_CANCELLED,
        IbkrOrderState.INACTIVE,
    }
)

# 送信後、終端状態に到達するまで能動的に監視する既定の上限秒数。
#
# 選定理由:
# - IBKR Paperの成行注文は、市場が開いていれば通常数秒〜数十秒以内に
#   何らかのorderStatus/execDetailsが届く。
# - 一方、市場時間外に送信された場合はPreSubmittedのまま長時間推移し得るため、
#   無限に待つのではなく一定時間で打ち切り、以降は補助的な
#   reconcile_order_via_readonly_query()による再接続照合に委ねる。
# - 30秒は「素早い応答を待つには十分」「一回限りのテスト実行の接続保持時間
#   としては過大でない」の両方を満たす値として選定した。
DEFAULT_CONFIRMATION_TIMEOUT_SECONDS = 30.0
DEFAULT_POLL_INTERVAL_SECONDS = 0.5

# 再接続照合の既定タイムアウト。reqExecutions/reqCompletedOrdersの
# 応答終了(execDetailsEnd/completedOrdersEnd)を待つか、この秒数で打ち切る。
DEFAULT_RECONCILIATION_TIMEOUT_SECONDS = 15.0

# IBKRが接続確立時などに定型的に送る情報メッセージ(エラーではない)。
BENIGN_INFO_ERROR_CODES = frozenset({2104, 2106, 2107, 2108, 2158})


@dataclass(frozen=True)
class IbkrFirstPaperConfirmationResult:
    status: str
    send_result: IbkrFirstPaperTestResult
    order_id: int | None
    reached_terminal: bool
    timed_out: bool
    last_known_status: str | None
    filled_quantity: float
    message: str


def send_and_confirm_first_paper_order(
    *,
    timeout_seconds: float = DEFAULT_CONFIRMATION_TIMEOUT_SECONDS,
    poll_interval_seconds: float = DEFAULT_POLL_INTERVAL_SECONDS,
    fill_state_path: str
    | Path = "data/ibkr_first_paper_test_fill_state.json",
    lock_path: str | Path = "data/ibkr_first_paper_test_send.lock",
    account_verification_timeout: float = (
        DEFAULT_ACCOUNT_VERIFICATION_TIMEOUT_SECONDS
    ),
    now_fn: Callable[[], float] = time.monotonic,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> IbkrFirstPaperConfirmationResult:
    """
    IbkrFirstPaperTestGateway.place_first_test_order()をそのまま使って
    AAPL BUY 1株の初回Paperテスト注文を送信し、送信後は固定秒数で
    切断するのではなく、終端状態
    (FILLED/CANCELLED/API_CANCELLED/INACTIVE)に到達するか
    timeout_secondsが経過するまで安全に状態を監視してから切断する。

    このモジュール自身は新しい発注ロジックを持たない。
    IbkrFirstPaperTestGateway/IbkrBrokerAdapterの送信経路・
    one-shot永続ロックをそのまま利用し、監視のための
    観測(オブザーバ)を追加するだけである。

    無限待機はしない。timeout_seconds経過後はTIMEOUTとして
    即座に切断・終了する(未確定であることを明示し、
    約定/取消と断定しない)。
    """
    gateway = IbkrFirstPaperTestGateway(
        enable_transmission=True,
        fill_state_path=fill_state_path,
        lock_path=lock_path,
        account_verification_timeout=account_verification_timeout,
    )

    if not gateway.connect():
        failed_send = IbkrFirstPaperTestResult(
            status="CONNECTION_FAILED",
            sent=False,
            order_id=None,
            message="IBKR Paperへの接続に失敗しました。",
        )
        return IbkrFirstPaperConfirmationResult(
            status="CONNECTION_FAILED",
            send_result=failed_send,
            order_id=None,
            reached_terminal=False,
            timed_out=False,
            last_known_status=None,
            filled_quantity=0.0,
            message="接続失敗のため送信していません。",
        )

    client = gateway._broker._session.client
    last_known_status: dict[int, str] = {}
    original_order_status = client.orderStatus

    def observing_order_status(
        orderId,
        status,
        filled,
        remaining,
        avgFillPrice,
        permId,
        parentId,
        lastFillPrice,
        clientId,
        whyHeld,
        mktCapPrice,
    ):
        last_known_status[int(orderId)] = str(status)
        return original_order_status(
            orderId,
            status,
            filled,
            remaining,
            avgFillPrice,
            permId,
            parentId,
            lastFillPrice,
            clientId,
            whyHeld,
            mktCapPrice,
        )

    client.orderStatus = observing_order_status

    # ===== 送信はここで1回だけ(既存のone-shotロック・固定条件をそのまま利用) =====
    send_result = gateway.place_first_test_order()

    if not send_result.sent or send_result.order_id is None:
        gateway.disconnect()
        return IbkrFirstPaperConfirmationResult(
            status="NOT_SENT",
            send_result=send_result,
            order_id=None,
            reached_terminal=False,
            timed_out=False,
            last_known_status=None,
            filled_quantity=0.0,
            message=send_result.message,
        )

    order_id = int(send_result.order_id)
    deadline = now_fn() + timeout_seconds
    reached_terminal = False

    while now_fn() < deadline:
        status_text = last_known_status.get(order_id)
        filled_quantity = gateway.order_status_snapshot(order_id)

        if (
            status_text is not None
            and normalize_ibkr_order_state(status_text) in TERMINAL_ORDER_STATES
        ):
            reached_terminal = True
            break

        if filled_quantity >= REQUIRED_QUANTITY:
            reached_terminal = True
            break

        sleep_fn(poll_interval_seconds)

    filled_quantity = gateway.order_status_snapshot(order_id)
    gateway.disconnect()

    return IbkrFirstPaperConfirmationResult(
        status="TERMINAL" if reached_terminal else "TIMEOUT",
        send_result=send_result,
        order_id=order_id,
        reached_terminal=reached_terminal,
        timed_out=not reached_terminal,
        last_known_status=last_known_status.get(order_id),
        filled_quantity=filled_quantity,
        message=(
            "終端状態に到達しました。"
            if reached_terminal
            else (
                f"{timeout_seconds}秒以内に終端状態へ到達しませんでした"
                "(未確定)。reconcile_order_via_readonly_query()による"
                "再接続照合を検討してください。"
            )
        ),
    )


@dataclass(frozen=True)
class IbkrOrderReconciliationResult:
    status: str
    order_id: int
    executions_found: list[dict]
    completed_order_found: bool
    error_codes: list[int]
    timed_out: bool
    message: str


def reconcile_order_via_readonly_query(
    order_id: int,
    *,
    fill_state_path: str | Path = "data/ibkr_first_paper_test_fill_state.json",
    timeout_seconds: float = DEFAULT_RECONCILIATION_TIMEOUT_SECONDS,
    now_fn: Callable[[], float] = time.monotonic,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> IbkrOrderReconciliationResult:
    """
    送信済みの注文について、再接続後にreqExecutions/reqCompletedOrdersで
    "補助的に"照合する。新規注文は一切送信しない。

    重要: 正常応答で0件だった場合、未約定・取消・失効とは解釈せず、
    必ずstatus="UNKNOWN"として扱う。エラーで取得できなかった場合のみ
    status="ERROR"とする。

    見つかった約定は、既存のIbkrFillRuntime(fill_state_pathで指定される
    永続状態)へexecId単位で冪等に反映し、実行を跨いだ取りこぼしを補完する。
    """
    config = IbkrConnectionConfig(
        host=REQUIRED_HOST,
        port=REQUIRED_PORT,
        client_id=REQUIRED_CLIENT_ID,
        paper_trading=True,
        allow_live_trading=False,
    )
    broker = IbkrBrokerAdapter(
        config,
        enable_paper_order_transmission=False,
        fill_state_path=fill_state_path,
    )

    if not broker.connect():
        return IbkrOrderReconciliationResult(
            status="CONNECTION_FAILED",
            order_id=order_id,
            executions_found=[],
            completed_order_found=False,
            error_codes=[],
            timed_out=False,
            message="IBKR Paperへの接続に失敗しました。",
        )

    client = broker._session.client

    def guarded_place_order(*args, **kwargs):
        raise RuntimeError(
            "SAFETY ABORT: 確認専用モジュールからplaceOrder()は呼べません。"
        )

    client.placeOrder = guarded_place_order

    executions_found: list[dict] = []
    completed_order_found = False
    error_codes: list[int] = []
    ends_seen = {"execDetailsEnd": False, "completedOrdersEnd": False}

    original_exec_details = client.execDetails
    original_exec_details_end = client.execDetailsEnd
    original_completed_order = client.completedOrder
    original_completed_orders_end = client.completedOrdersEnd
    original_error = client.error

    def on_exec_details(reqId, contract, execution):
        if int(execution.orderId) == order_id:
            executions_found.append(
                {
                    "execId": str(execution.execId),
                    "shares": float(execution.shares),
                    "price": float(execution.price),
                }
            )
        return original_exec_details(reqId, contract, execution)

    def on_exec_details_end(reqId):
        ends_seen["execDetailsEnd"] = True
        return original_exec_details_end(reqId)

    def on_completed_order(contract, order, orderState):
        nonlocal completed_order_found
        if int(order.orderId) == order_id:
            completed_order_found = True
        return original_completed_order(contract, order, orderState)

    def on_completed_orders_end():
        ends_seen["completedOrdersEnd"] = True
        return original_completed_orders_end()

    def on_error(
        reqId, errorTime, errorCode, errorString, advancedOrderRejectJson=""
    ):
        error_codes.append(int(errorCode))
        return original_error(
            reqId, errorTime, errorCode, errorString, advancedOrderRejectJson
        )

    client.execDetails = on_exec_details
    client.execDetailsEnd = on_exec_details_end
    client.completedOrder = on_completed_order
    client.completedOrdersEnd = on_completed_orders_end
    client.error = on_error

    exec_filter = ExecutionFilter()
    exec_filter.clientId = REQUIRED_CLIENT_ID

    # ===== 読み取り専用リクエストのみ =====
    client.reqExecutions(9301, exec_filter)
    client.reqCompletedOrders(False)

    deadline = now_fn() + timeout_seconds
    got_both_ends = False
    while now_fn() < deadline:
        if ends_seen["execDetailsEnd"] and ends_seen["completedOrdersEnd"]:
            got_both_ends = True
            break
        sleep_fn(0.2)
    timed_out = not got_both_ends

    if executions_found:
        # process_execution()は登録済みの注文にしか反映しないため、
        # この確認専用フローでは初回Paperテストの固定内容
        # (AAPL/BUY/1株)で登録してから反映する。
        broker._fill_runtime.register_order(
            order_id,
            OrderRequest(
                symbol=REQUIRED_SYMBOL,
                side=REQUIRED_SIDE,
                quantity=REQUIRED_QUANTITY,
            ),
        )

    for execution in executions_found:
        broker._fill_runtime.process_execution(
            order_id,
            execution["execId"],
            execution["shares"],
            execution["price"],
        )

    broker.disconnect()

    blocking_errors = [
        code for code in error_codes if code not in BENIGN_INFO_ERROR_CODES
    ]

    if blocking_errors:
        status = "ERROR"
        message = f"読み取り専用リクエストでエラーが発生しました: {blocking_errors}"
    elif executions_found or completed_order_found:
        status = "FOUND"
        message = "再接続照合で記録が見つかりました。"
    elif timed_out:
        status = "UNKNOWN"
        message = (
            f"{timeout_seconds}秒以内にreqExecutions/reqCompletedOrdersの"
            "応答完了を確認できませんでした(未確定)。"
            "未約定・取消・失効とは断定せず、確認不能として扱います。"
        )
    else:
        status = "UNKNOWN"
        message = (
            "正常応答でしたが記録は見つかりませんでした。"
            "未約定・取消・失効とは断定せず、確認不能として扱います。"
        )

    return IbkrOrderReconciliationResult(
        status=status,
        order_id=order_id,
        executions_found=executions_found,
        completed_order_found=completed_order_found,
        error_codes=error_codes,
        timed_out=timed_out,
        message=message,
    )

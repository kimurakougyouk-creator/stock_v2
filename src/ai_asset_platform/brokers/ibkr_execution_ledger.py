from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class IbkrExecutionLedger:
    """
    IBKRのexecDetailsをexecId単位で冪等に管理し、
    注文ごとの累積約定株数と加重平均約定価格を計算する。

    同じexecIdを複数回受け取っても(reqExecutions再取得等)、
    合計・加重平均には影響しない。
    """

    _executions: dict[int, dict[str, tuple[float, float]]] = field(
        default_factory=dict
    )

    def record_execution(
        self,
        order_id: int,
        exec_id: str,
        shares: float,
        price: float,
    ) -> tuple[float, float]:
        """execIdを冪等に記録し、(累積株数, 加重平均価格)を返す。"""
        if order_id < 0:
            raise ValueError("IBKR order_idは0以上にしてください。")

        if not exec_id:
            raise ValueError("IBKR execIdが空です。")

        if shares <= 0:
            raise ValueError("IBKR約定株数は0より大きくしてください。")

        if price <= 0:
            raise ValueError("IBKR約定価格は0より大きくしてください。")

        order_executions = self._executions.setdefault(order_id, {})
        order_executions[exec_id] = (float(shares), float(price))

        return self._cumulative(order_id)

    def cumulative(self, order_id: int) -> tuple[float, float]:
        return self._cumulative(order_id)

    def _cumulative(self, order_id: int) -> tuple[float, float]:
        order_executions = self._executions.get(order_id, {})

        total_shares = sum(shares for shares, _ in order_executions.values())

        if total_shares <= 0:
            return 0.0, 0.0

        total_amount = sum(
            shares * price for shares, price in order_executions.values()
        )

        return total_shares, total_amount / total_shares

    def snapshot(self) -> dict[int, dict[str, tuple[float, float]]]:
        return {
            order_id: dict(executions)
            for order_id, executions in self._executions.items()
        }

    def restore(
        self,
        data: dict[int, dict[str, tuple[float, float]]],
    ) -> None:
        restored: dict[int, dict[str, tuple[float, float]]] = {}

        for order_id, executions in data.items():
            if int(order_id) < 0:
                raise ValueError("IBKR order_idは0以上にしてください。")

            restored_executions: dict[str, tuple[float, float]] = {}

            for exec_id, (shares, price) in executions.items():
                if shares <= 0 or price <= 0:
                    raise ValueError("IBKR約定データが不正です。")
                restored_executions[str(exec_id)] = (
                    float(shares),
                    float(price),
                )

            restored[int(order_id)] = restored_executions

        self._executions = restored

    def clear(self, order_id: int) -> None:
        self._executions.pop(order_id, None)

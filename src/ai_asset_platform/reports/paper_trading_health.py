from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PaperTradingHealth:
    status: str
    message: str
    signal_count: int
    error_count: int


def evaluate_paper_trading_health(
    *,
    signal_count: int,
    error_count: int,
) -> PaperTradingHealth:
    """
    Paper Trading 1回分の実行結果を簡単に診断する。

    NORMAL:
        シグナル取得あり、エラーなし

    WARNING:
        シグナルが0件

    ERROR:
        1件以上のエラーあり
    """

    signal_count = int(signal_count)
    error_count = int(error_count)

    if signal_count < 0:
        raise ValueError("signal_countは0以上にしてください。")

    if error_count < 0:
        raise ValueError("error_countは0以上にしてください。")

    if error_count > 0:
        return PaperTradingHealth(
            status="ERROR",
            message=f"Paper Tradingで{error_count}件のエラーが発生しました。",
            signal_count=signal_count,
            error_count=error_count,
        )

    if signal_count == 0:
        return PaperTradingHealth(
            status="WARNING",
            message="Paper Tradingは終了しましたが、シグナルが0件です。",
            signal_count=signal_count,
            error_count=error_count,
        )

    return PaperTradingHealth(
        status="NORMAL",
        message="Paper Tradingは正常です。",
        signal_count=signal_count,
        error_count=error_count,
    )

"""
Paper Trading専用ランナー。

安全方針:
- Paper Tradingが有効な場合だけ実行する
- Live Tradingが解除されている場合は実行しない
- 注文許可はこの入口からだけ明示的にONにする
"""

from ai_asset_platform.core.settings import SETTINGS
from ai_asset_platform.execution.paper_trading_loop import run_paper_trading_loop
from ai_asset_platform.reports.paper_trading_health import evaluate_paper_trading_health
from signal_runner import _create_configured_ai_provider, run_signal_scan


def run_paper_trading() -> dict:
    if not SETTINGS.enable_paper_trading:
        raise RuntimeError(
            "Paper Tradingが無効です。実行を中止しました。"
        )

    if SETTINGS.enable_live_trading:
        raise RuntimeError(
            "Live Tradingが有効なため、"
            "安全のためPaper試運転を中止しました。"
        )

    if SETTINGS.live_trading_unlocked:
        raise RuntimeError(
            "Live Tradingが解除されているため、"
            "安全のためPaper試運転を中止しました。"
        )

    ai_provider = _create_configured_ai_provider()

    return run_signal_scan(
        ai_provider=ai_provider,
        allow_orders=True,
        allow_email=False,
    )



def run_continuous_paper_trading(
    *,
    max_runs: int = 3,
):
    """
    Paper Tradingを安全に複数回実行する。

    ERRORを検出した場合は自動停止する。
    """

    return run_paper_trading_loop(
        run_once=run_paper_trading,
        max_runs=max_runs,
    )

def main() -> None:
    print("=" * 50)
    print("AI Asset Platform - PAPER TRADING")
    print("Live Trading : OFF")
    print("Paper Orders : ON")
    print("=" * 50)

    result = run_paper_trading()

    signal_count = len(result["records"])
    error_count = len(result["errors"])

    health = evaluate_paper_trading_health(
        signal_count=signal_count,
        error_count=error_count,
    )

    print("=" * 50)
    print("Paper Trading実行結果")
    print(f"診断結果    : {health.status}")
    print(f"状態        : {health.message}")
    print(f"シグナル件数: {health.signal_count}")
    print(f"エラー件数  : {health.error_count}")
    print("=" * 50)


if __name__ == "__main__":
    main()

"""
Paper Trading専用ランナー。

安全方針:
- Paper Tradingが有効な場合だけ実行する
- Live Tradingが解除されている場合は実行しない
- 注文許可はこの入口からだけ明示的にONにする
"""

from ai_asset_platform.core.settings import SETTINGS
from signal_runner import _create_configured_ai_provider, run_signal_scan


def run_paper_trading() -> dict:
    if not SETTINGS.enable_paper_trading:
        raise RuntimeError(
            "Paper Tradingが無効です。実行を中止しました。"
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


def main() -> None:
    print("=" * 50)
    print("AI Asset Platform - PAPER TRADING")
    print("Live Trading : OFF")
    print("Paper Orders : ON")
    print("=" * 50)

    result = run_paper_trading()

    print("=" * 50)
    print("Paper Trading正常終了")
    print(f"シグナル件数: {len(result['records'])}")
    print(f"エラー件数  : {len(result['errors'])}")
    print("=" * 50)


if __name__ == "__main__":
    main()

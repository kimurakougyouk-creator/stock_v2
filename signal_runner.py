from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
import yfinance as yf

from ai_asset_platform.ai import (
    create_provider,
    judge_with_ai,
    load_ai_settings,
)
from ai_asset_platform.decision import determine_final_decision
from config import (
    APP_PASSWORD,
    EMAIL_ADDRESS,
    INTERVAL,
    LOT_SIZE,
    PERIOD,
    TRADING_CAPITAL,
)
from ai_asset_platform.core.settings import SETTINGS
from indicators import add_indicators
from mail import send_mail
from order_manager import (
    calculate_available_cash,
    calculate_consecutive_losses,
    calculate_daily_buy_order_count,
    calculate_daily_realized_pnl,
    calculate_daily_sell_order_count,
    calculate_daily_trading_amount,
    calculate_repurchase_cooldown_remaining_minutes,
    create_paper_order,
    get_open_positions,
)
from optimization_settings import get_ticker_settings, load_optimized_settings
from report_formatter import format_signal_report
from signal_engine import determine_signal


def _get_result_dir() -> Path:
    result_dir = Path("results")
    result_dir.mkdir(exist_ok=True)
    return result_dir


def _safe_download(ticker: str) -> tuple[pd.DataFrame | None, str | None]:
    try:
        df = yf.download(ticker, period=PERIOD, interval=INTERVAL, auto_adjust=True)
    except Exception as exc:  # pragma: no cover - defensive path
        return None, str(exc)

    if hasattr(df.columns, "nlevels") and df.columns.nlevels > 1:
        df.columns = df.columns.get_level_values(0)

    if df.empty:
        return None, "empty"

    return df, None


def run_signal_scan(
    tickers: list[str] | None = None,
    *,
    ai_provider: Any | None = None,
    allow_orders: bool = False,
    allow_email: bool = True,
) -> dict[str, Any]:
    if tickers is None:
        ticker_df = pd.read_csv("tickers.csv")
        tickers = ticker_df["Ticker"].tolist()

    all_settings = load_optimized_settings()
    records: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    for ticker in tickers:
        df, error = _safe_download(ticker)
        if df is None:
            errors.append({"ticker": ticker, "error": error or "unknown"})
            print(f"{ticker}: データ取得に失敗しました。処理をスキップします。")
            continue

        try:
            settings = get_ticker_settings(ticker, all_settings)
            prepared = add_indicators(
                df.copy(),
                ma_short=settings["ma_short"],
                ma_middle=settings["ma_middle"],
                ma_long=settings["ma_long"],
            )
            signal_result = determine_signal(
                prepared,
                rsi_low=settings["rsi_low"],
                rsi_high=settings["rsi_high"],
                atr_multiplier=settings["atr_multiplier"],
            )

            ai_result = judge_with_ai(
                {
                    "ticker": ticker,
                    "technical_signal": signal_result["signal"],
                    "score": signal_result["score"],
                    "price": signal_result["price"],
                    "ma_short": signal_result["ma_short"],
                    "ma_middle": signal_result["ma_middle"],
                    "ma_long": signal_result["ma_long"],
                    "rsi": signal_result["rsi"],
                    "macd": signal_result["macd"],
                    "signal_line": signal_result["signal_line"],
                    "atr": signal_result["atr"],
                    "grade": signal_result["grade"],
                    "stop_price": signal_result["stop_price"],
                },
                provider=ai_provider,
            )

            final_decision = determine_final_decision(
                signal_result["signal"],
                ai_result,
            )

            if allow_orders and final_decision.signal in {"BUY", "SELL"}:
                if SETTINGS.emergency_stop:
                    print(
                        f"{ticker}: 緊急停止が有効なため、"
                        "注文を見送りました。"
                    )
                else:
                    shares = int(signal_result["reference_shares"] or 0)
                    positions = get_open_positions()
                    held_shares = int(positions.get(ticker, 0))

                    daily_realized_pnl = calculate_daily_realized_pnl()
                    daily_loss_limit_yen = float(
                        getattr(SETTINGS, "daily_loss_limit_yen", 0.0)
                    )
                    daily_loss_limit_reached = (
                        daily_loss_limit_yen > 0
                        and daily_realized_pnl <= -daily_loss_limit_yen
                    )

                    max_consecutive_losses = int(
                        getattr(SETTINGS, "max_consecutive_losses", 0)
                    )
                    consecutive_losses = (
                        calculate_consecutive_losses()
                        if max_consecutive_losses > 0
                        else 0
                    )
                    consecutive_loss_limit_reached = (
                        max_consecutive_losses > 0
                        and consecutive_losses >= max_consecutive_losses
                    )

                    max_positions = int(
                        getattr(SETTINGS, "max_positions", 0)
                    )
                    current_position_count = len(positions)
                    max_positions_reached = (
                        max_positions > 0
                        and current_position_count >= max_positions
                    )

                    max_daily_buy_orders = int(
                        getattr(SETTINGS, "max_daily_buy_orders", 0)
                    )
                    daily_buy_order_count = (
                        calculate_daily_buy_order_count()
                        if max_daily_buy_orders > 0
                        else 0
                    )
                    daily_buy_limit_reached = (
                        max_daily_buy_orders > 0
                        and daily_buy_order_count >= max_daily_buy_orders
                    )

                    max_daily_sell_orders = int(
                        getattr(SETTINGS, "max_daily_sell_orders", 0)
                    )
                    daily_sell_order_count = (
                        calculate_daily_sell_order_count()
                        if max_daily_sell_orders > 0
                        else 0
                    )
                    daily_sell_limit_reached = (
                        max_daily_sell_orders > 0
                        and daily_sell_order_count >= max_daily_sell_orders
                    )

                    repurchase_cooldown_minutes = int(
                        getattr(
                            SETTINGS,
                            "repurchase_cooldown_minutes",
                            0,
                        )
                    )
                    repurchase_cooldown_remaining = (
                        calculate_repurchase_cooldown_remaining_minutes(
                            ticker,
                            repurchase_cooldown_minutes,
                        )
                        if (
                            final_decision.signal == "BUY"
                            and repurchase_cooldown_minutes > 0
                        )
                        else 0
                    )

                    if (
                        final_decision.signal == "BUY"
                        and daily_loss_limit_reached
                    ):
                        print(
                            f"{ticker}: 本日の確定損益が"
                            f"{daily_realized_pnl:,.0f}円となり、"
                            f"1日の損失上限"
                            f"{daily_loss_limit_yen:,.0f}円に達したため、"
                            "新規BUY注文を見送りました。"
                        )
                    elif (
                        final_decision.signal == "BUY"
                        and consecutive_loss_limit_reached
                    ):
                        print(
                            f"{ticker}: 現在{consecutive_losses}連敗しており、"
                            f"最大連敗回数"
                            f"{max_consecutive_losses}回に達したため、"
                            "新規BUY注文を見送りました。"
                        )
                    elif (
                        final_decision.signal == "BUY"
                        and daily_buy_limit_reached
                    ):
                        print(
                            f"{ticker}: 本日の新規BUY注文が"
                            f"{daily_buy_order_count}回となり、"
                            f"1日の上限"
                            f"{max_daily_buy_orders}回に達したため、"
                            "新規BUY注文を見送りました。"
                        )
                    elif (
                        final_decision.signal == "BUY"
                        and repurchase_cooldown_remaining > 0
                    ):
                        print(
                            f"{ticker}: 直近のSELL注文からの"
                            "再購入クールダウン中です。"
                            f"あと約{repurchase_cooldown_remaining}分間、"
                            "新規BUY注文を見送ります。"
                        )
                    elif final_decision.signal == "BUY" and held_shares > 0:
                        print(
                            f"{ticker}: 最終BUY判定ですが、"
                            f"すでに{held_shares}株保有しているため注文を見送りました。"
                        )
                    elif (
                        final_decision.signal == "BUY"
                        and held_shares <= 0
                        and max_positions_reached
                    ):
                        print(
                            f"{ticker}: 現在の保有銘柄数が"
                            f"{current_position_count}銘柄となり、"
                            f"最大保有銘柄数"
                            f"{max_positions}銘柄に達したため、"
                            "新規BUY注文を見送りました。"
                        )
                    elif (
                        final_decision.signal == "SELL"
                        and daily_sell_limit_reached
                    ):
                        print(
                            f"{ticker}: 本日のSELL注文が"
                            f"{daily_sell_order_count}回となり、"
                            f"1日の上限"
                            f"{max_daily_sell_orders}回に達したため、"
                            "SELL注文を見送りました。"
                        )
                    elif final_decision.signal == "SELL" and held_shares <= 0:
                        print(
                            f"{ticker}: 最終SELL判定ですが、"
                            "保有していないため注文を見送りました。"
                        )
                    elif shares > 0:
                        max_order_shares = int(
                            getattr(SETTINGS, "max_order_shares", shares)
                        )
                        order_shares = min(shares, max_order_shares)

                        if final_decision.signal == "BUY":
                            reference_price = float(
                                signal_result["price"]
                            )
                            available_cash = calculate_available_cash(
                                TRADING_CAPITAL
                            )

                            max_portfolio_allocation = float(
                                getattr(
                                    SETTINGS,
                                    "max_portfolio_allocation",
                                    1.0,
                                )
                            )
                            max_portfolio_allocation = max(
                                0.0,
                                min(1.0, max_portfolio_allocation),
                            )

                            minimum_cash_reserve = (
                                float(TRADING_CAPITAL)
                                * (1.0 - max_portfolio_allocation)
                            )
                            portfolio_buying_power = max(
                                0.0,
                                available_cash - minimum_cash_reserve,
                            )

                            affordable_shares = int(
                                portfolio_buying_power // reference_price
                            )
                            affordable_shares = (
                                affordable_shares // LOT_SIZE
                            ) * LOT_SIZE

                            max_position_allocation = float(
                                getattr(
                                    SETTINGS,
                                    "max_position_allocation",
                                    1.0,
                                )
                            )
                            if max_position_allocation <= 0:
                                allocation_limit_yen = 0.0
                            elif max_position_allocation >= 1:
                                allocation_limit_yen = float(
                                    TRADING_CAPITAL
                                )
                            else:
                                allocation_limit_yen = (
                                    float(TRADING_CAPITAL)
                                    * max_position_allocation
                                )

                            allocation_limit_shares = int(
                                allocation_limit_yen // reference_price
                            )
                            allocation_limit_shares = (
                                allocation_limit_shares // LOT_SIZE
                            ) * LOT_SIZE

                            order_shares = min(
                                order_shares,
                                affordable_shares,
                                allocation_limit_shares,
                            )

                        if final_decision.signal == "SELL":
                            order_shares = min(
                                order_shares,
                                held_shares,
                            )

                        if (
                            final_decision.signal == "BUY"
                            and order_shares <= 0
                        ):
                            print(
                                f"{ticker}: 利用可能資金、"
                                "ポートフォリオ全体の投資比率上限、または"
                                "1銘柄あたりの資金配分上限では"
                                f"{LOT_SIZE}株以上購入できないため、"
                                "新規BUY注文を見送りました。"
                            )
                        elif order_shares <= 0:
                            print(
                                f"{ticker}: 注文数量上限により、"
                                "注文を見送りました。"
                            )
                        else:
                            max_daily_trading_amount_yen = float(
                                getattr(
                                    SETTINGS,
                                    "max_daily_trading_amount_yen",
                                    0.0,
                                )
                            )
                            daily_trading_amount = (
                                calculate_daily_trading_amount()
                                if max_daily_trading_amount_yen > 0
                                else 0.0
                            )
                            planned_order_amount = (
                                float(signal_result["price"])
                                * order_shares
                            )
                            projected_daily_trading_amount = (
                                daily_trading_amount
                                + planned_order_amount
                            )

                            if (
                                max_daily_trading_amount_yen > 0
                                and projected_daily_trading_amount
                                > max_daily_trading_amount_yen
                            ):
                                print(
                                    f"{ticker}: 本日の売買代金"
                                    f"{daily_trading_amount:,.0f}円に、"
                                    f"今回の注文予定額"
                                    f"{planned_order_amount:,.0f}円を加えると、"
                                    f"1日の総取引金額上限"
                                    f"{max_daily_trading_amount_yen:,.0f}円を"
                                    "超えるため、注文を見送りました。"
                                )
                            elif SETTINGS.enable_paper_trading:
                                paper_order = create_paper_order(
                                    ticker=ticker,
                                    signal=final_decision.signal,
                                    shares=order_shares,
                                    reference_price=float(signal_result["price"]),
                                )
                                print(
                                    f"{ticker}: AI最終判定による模擬注文を記録しました "
                                    f"({paper_order['side']} "
                                    f"{paper_order['shares']}株)"
                                )
                            elif SETTINGS.live_trading_unlocked:
                                print(
                                    f"{ticker}: 本番取引の安全ロックは"
                                    "解除されていますが、"
                                    "本番注文機能は未実装のため注文しません。"
                                )
                            else:
                                print(
                                    f"{ticker}: 取引モードの安全ロックにより、"
                                    "注文を見送りました。"
                                )
                    else:
                        print(
                            f"{ticker}: 最終{final_decision.signal}判定ですが、"
                            "資金管理により注文を見送りました。"
                        )

            record = {
                "Ticker": ticker,
                "Signal": signal_result["signal"],
                "Reason": signal_result["reason"],
                "Close": signal_result["price"],
                "MA5": signal_result["ma_short"],
                "MA25": signal_result["ma_middle"],
                "MA75": signal_result["ma_long"],
                "RSI": signal_result["rsi"],
                "MACD": signal_result["macd"],
                "SignalLine": signal_result["signal_line"],
                "ATR": signal_result["atr"],
                "Score": signal_result["score"],
                "Grade": signal_result["grade"],
                "StopPrice": signal_result["stop_price"],
                "RiskPerShare": signal_result["risk_per_share"],
                "MaxLossYen": signal_result["max_loss_yen"],
                "ReferenceShares": signal_result["reference_shares"],
                "ReferenceAmountYen": signal_result["reference_amount_yen"],
                "PositionSizingReason": signal_result["position_sizing_reason"],
                "AISignal": ai_result.signal,
                "AIScore": ai_result.score,
                "AIConfidence": ai_result.confidence,
                "AIReason": ai_result.reason,
                "AIProvider": ai_result.provider,
                "AIAvailable": ai_result.available,
                "FinalSignal": final_decision.signal,
                "FinalReason": final_decision.reason,
            }
            records.append(record)
            print(
                f"{ticker}: "
                f"テクニカル={signal_result['signal']} / "
                f"AI={ai_result.signal} / "
                f"最終={final_decision.signal}"
            )
        except Exception as exc:  # pragma: no cover - defensive path
            errors.append({"ticker": ticker, "error": str(exc)})
            record = {
                "Ticker": ticker,
                "Signal": "HOLD",
                "Reason": f"判定中にエラーが発生したため、HOLDとして扱います。{exc}",
                "Close": None,
                "MA5": None,
                "MA25": None,
                "MA75": None,
                "RSI": None,
                "MACD": None,
                "SignalLine": None,
                "ATR": None,
                "Score": 0,
                "Grade": "E",
                "StopPrice": None,
                "RiskPerShare": None,
                "MaxLossYen": None,
                "ReferenceShares": 0,
                "ReferenceAmountYen": None,
                "PositionSizingReason": "判定エラーのため、参考株数は0です。",
                "AISignal": "HOLD",
                "AIScore": 50.0,
                "AIConfidence": 0.0,
                "AIReason": "テクニカル判定中にエラーが発生したため、AI評価を行いませんでした。",
                "AIProvider": "none",
                "AIAvailable": False,
                "FinalSignal": "HOLD",
                "FinalReason": "判定エラーのため、安全側でHOLDとします。",
            }
            records.append(record)
            print(f"{ticker}: 判定中にエラーが発生しました。{exc}")

    output_df = pd.DataFrame(records)
    for numeric_column in [
        "Score",
        "StopPrice",
        "RiskPerShare",
        "MaxLossYen",
        "ReferenceShares",
        "ReferenceAmountYen",
        "AIScore",
        "AIConfidence",
    ]:
        output_df[numeric_column] = pd.to_numeric(output_df[numeric_column], errors="coerce").fillna(0)

    output_df = output_df.sort_values(["Score", "Ticker"], ascending=[False, True], kind="mergesort").reset_index(drop=True)
    output_df.insert(output_df.columns.get_loc("Score") + 1, "Rank", range(1, len(output_df) + 1))

    output_dir = _get_result_dir()
    output_path = output_dir / "latest_signals.xlsx"
    output_df.to_excel(output_path, index=False)

    if output_path.exists():
        format_signal_report(output_path)

    if not output_df.empty:
        actionable = output_df[
            output_df["FinalSignal"].isin(["BUY", "SELL"])
        ]
        if not actionable.empty and not allow_email:
            print("AI最終BUY/SELL判定はありますが、メール通知は無効です。")
        elif not actionable.empty:
            subject = "AI最終売買判定通知"
            body_lines = ["AI統合後の最新売買判定一覧です。", ""]

            for _, row in actionable.iterrows():
                body_lines.append(
                    f"【{row['Ticker']}】最終判定: {row['FinalSignal']}"
                )
                body_lines.append(f"テクニカル判定: {row['Signal']}")
                body_lines.append(f"AI判定: {row['AISignal']}")
                body_lines.append(
                    f"AI信頼度: {float(row['AIConfidence']):.1f}%"
                )
                body_lines.append(f"AI提供元: {row['AIProvider']}")
                body_lines.append(f"スコア: {int(row['Score'])}点")
                body_lines.append(f"評価: {row['Grade']}")
                body_lines.append(f"順位: {int(row['Rank'])}位")
                body_lines.append(f"現在価格: {float(row['Close']):,.1f}円")
                body_lines.append(f"参考株数: {int(row['ReferenceShares'])}株")
                body_lines.append(
                    f"参考購入金額: {float(row['ReferenceAmountYen']):,.0f}円"
                )

                if row["FinalSignal"] == "BUY":
                    body_lines.append(
                        f"損切り参考価格: {float(row['StopPrice']):,.1f}円"
                    )
                    body_lines.append(
                        f"最大許容損失額: {float(row['MaxLossYen']):,.0f}円"
                    )
                    body_lines.append(
                        f"株数の計算理由: {row['PositionSizingReason']}"
                    )

                body_lines.append("")
                body_lines.append("テクニカル判定理由:")
                for reason in str(row["Reason"]).split("｜"):
                    if reason:
                        body_lines.append(f"・{reason}")

                body_lines.append("")
                body_lines.append("AI判定理由:")
                body_lines.append(f"・{row['AIReason']}")

                body_lines.append("")
                body_lines.append("最終判定理由:")
                body_lines.append(f"・{row['FinalReason']}")

                body_lines.append("")
                body_lines.append("--------------------")
                body_lines.append("")

            send_mail(
                EMAIL_ADDRESS,
                APP_PASSWORD,
                EMAIL_ADDRESS,
                subject,
                "\n".join(body_lines),
            )
            print("AI最終BUY/SELL判定をメールで通知しました。")
        else:
            print("AI最終BUY/SELL判定はありませんでした.")
    else:
        print("シグナルがありませんでした。")

    if errors:
        print("一部銘柄でエラーが発生しました。")

    summary_message = (
        f"シグナル件数: {len(records)}件 / 取得失敗: {len(errors)}件"
    )
    print(summary_message)

    return {
        "records": records,
        "errors": errors,
        "output_path": str(output_path),
        "summary_message": summary_message,
    }


def _create_configured_ai_provider() -> Any | None:
    """環境設定からAIプロバイダーを安全に作成する。"""

    try:
        settings = load_ai_settings()

        if not settings.is_available:
            print("AI設定が未設定のため、AI評価はスキップします。")
            return None

        provider = create_provider(
            settings.provider,
            model=settings.get_model(),
            api_key=settings.get_api_key(),
        )

        print(
            f"AI評価を有効化しました: "
            f"{settings.provider} / {settings.get_model()}"
        )
        return provider
    except Exception as exc:
        print(
            "AI設定の読み込みに失敗したため、"
            f"AI評価をスキップします。{exc}"
        )
        return None


def main() -> None:
    ai_provider = _create_configured_ai_provider()
    result = run_signal_scan(ai_provider=ai_provider)
    if EMAIL_ADDRESS and APP_PASSWORD:
        if result["records"]:
            if any(record["Signal"] in {"BUY", "SELL"} for record in result["records"]):
                print("シグナル分析が完了しました。")
            else:
                print("HOLDのみでしたが、シグナル分析は正常終了しました。")
        else:
            print("シグナルがありませんでしたが、処理は正常終了しました。")
    else:
        print("メール設定が未設定のため、通知はスキップしました。")


if __name__ == "__main__":
    main()

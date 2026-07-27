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
from config import EMAIL_ADDRESS, APP_PASSWORD, INTERVAL, PERIOD
from ai_asset_platform.core.settings import SETTINGS
from indicators import add_indicators
from mail import send_mail
from order_manager import create_paper_order, get_open_positions
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

                    if final_decision.signal == "BUY" and held_shares > 0:
                        print(
                            f"{ticker}: 最終BUY判定ですが、"
                            f"すでに{held_shares}株保有しているため注文を見送りました。"
                        )
                    elif final_decision.signal == "SELL" and held_shares <= 0:
                        print(
                            f"{ticker}: 最終SELL判定ですが、"
                            "保有していないため注文を見送りました。"
                        )
                    elif shares > 0:
                        order_shares = (
                            min(shares, held_shares)
                            if final_decision.signal == "SELL"
                            else shares
                        )
                        if SETTINGS.enable_paper_trading:
                            paper_order = create_paper_order(
                                ticker=ticker,
                                signal=final_decision.signal,
                                shares=order_shares,
                                reference_price=float(signal_result["price"]),
                            )
                            print(
                                f"{ticker}: AI最終判定による模擬注文を記録しました "
                                f"({paper_order['side']} {paper_order['shares']}株)"
                            )
                        elif SETTINGS.live_trading_unlocked:
                            print(
                                f"{ticker}: 本番取引の安全ロックは解除されていますが、"
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

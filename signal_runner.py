from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
import yfinance as yf

from config import EMAIL_ADDRESS, APP_PASSWORD, INTERVAL, PERIOD
from indicators import add_indicators
from mail import send_mail
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


def run_signal_scan(tickers: list[str] | None = None) -> dict[str, Any]:
    if tickers is None:
        ticker_df = pd.read_csv("tickers.csv")
        tickers = ticker_df["Ticker"].tolist()

    records: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    for ticker in tickers:
        df, error = _safe_download(ticker)
        if df is None:
            errors.append({"ticker": ticker, "error": error or "unknown"})
            print(f"{ticker}: データ取得に失敗しました。処理をスキップします。")
            continue

        try:
            prepared = add_indicators(df.copy())
            signal_result = determine_signal(prepared)
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
            }
            records.append(record)
            print(f"{ticker}: {signal_result['signal']}")
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
            }
            records.append(record)
            print(f"{ticker}: 判定中にエラーが発生しました。{exc}")

    output_df = pd.DataFrame(records)
    for numeric_column in ["Score", "StopPrice", "RiskPerShare", "MaxLossYen", "ReferenceShares", "ReferenceAmountYen"]:
        output_df[numeric_column] = pd.to_numeric(output_df[numeric_column], errors="coerce").fillna(0)

    output_df = output_df.sort_values(["Score", "Ticker"], ascending=[False, True], kind="mergesort").reset_index(drop=True)
    output_df.insert(output_df.columns.get_loc("Score") + 1, "Rank", range(1, len(output_df) + 1))

    output_dir = _get_result_dir()
    output_path = output_dir / "latest_signals.xlsx"
    output_df.to_excel(output_path, index=False)

    if not output_df.empty:
        actionable = output_df[output_df["Signal"].isin(["BUY", "SELL"])]
        if not actionable.empty:
            subject = "売買シグナル通知"
            body_lines = ["最新のシグナル一覧です。", ""]
            for _, row in actionable.iterrows():
                summary = f"- {row['Ticker']}: {row['Signal']} (Score {int(row['Score'])}, Rank {int(row['Rank'])}, 参考株数 {int(row['ReferenceShares'])})"
                if row["Signal"] == "BUY" and int(row["ReferenceShares"]) == 0:
                    summary += f" - {row['PositionSizingReason']}"
                body_lines.append(summary)
            send_mail(EMAIL_ADDRESS, APP_PASSWORD, EMAIL_ADDRESS, subject, "\n".join(body_lines))
            print("BUY/SELLシグナルをメールで通知しました。")
        else:
            print("BUY/SELLシグナルはありませんでした。")
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


def main() -> None:
    result = run_signal_scan()
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

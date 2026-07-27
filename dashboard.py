from __future__ import annotations

import html
import os
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from config import TRADING_CAPITAL


def _format_currency(value: Any) -> str:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return "-"
    if numeric == 0:
        return "0"
    return f"{numeric:,.0f}"


def _safe_read_signal_excel(base_dir: Path) -> pd.DataFrame:
    signal_path = base_dir / "latest_signals.xlsx"
    if not signal_path.exists():
        return pd.DataFrame()

    try:
        df = pd.read_excel(signal_path)
    except Exception:
        return pd.DataFrame()

    if df.empty:
        return pd.DataFrame()

    return df


def _safe_read_summary_excel(base_dir: Path) -> dict[str, Any]:
    summary_path = base_dir / "summary.xlsx"
    if not summary_path.exists():
        return {}

    try:
        summary_df = pd.read_excel(summary_path)
    except Exception:
        return {}

    if summary_df.empty:
        return {}

    columns = {str(col).lower(): col for col in summary_df.columns}
    values: dict[str, Any] = {}
    for key in ["summary", "message", "note"]:
        if key in columns:
            values[key] = summary_df.iloc[0][columns[key]]
    return values


def build_dashboard_html(base_dir: Path | None = None) -> str:
    base_dir = Path(base_dir or Path("results"))
    base_dir.mkdir(exist_ok=True, parents=True)

    signal_df = _safe_read_signal_excel(base_dir)
    summary_info = _safe_read_summary_excel(base_dir)

    if signal_df.empty:
        rows = []
        errors = []
        buy_count = sell_count = hold_count = 0
        highest_score = 0.0
        average_score = 0.0
        summary_text = "シグナルデータが取得できませんでした。"
    else:
        columns = {col: col for col in signal_df.columns}
        rows = []
        errors = []
        buy_count = int((signal_df["Signal"].astype(str).str.upper() == "BUY").sum()) if "Signal" in columns else 0
        sell_count = int((signal_df["Signal"].astype(str).str.upper() == "SELL").sum()) if "Signal" in columns else 0
        hold_count = int((signal_df["Signal"].astype(str).str.upper() == "HOLD").sum()) if "Signal" in columns else 0
        highest_score = float(signal_df["Score"].astype(float).max()) if "Score" in columns and not signal_df["Score"].empty else 0.0
        average_score = float(signal_df["Score"].astype(float).mean()) if "Score" in columns and not signal_df["Score"].empty else 0.0
        summary_text = str(summary_info.get("summary") or summary_info.get("message") or summary_info.get("note") or "")

        for _, row in signal_df.iterrows():
            row_data = {}
            for key in [
                "Ticker",
                "Signal",
                "FinalSignal",
                "AIConfidence",
                "AIReason",
                "FinalReason",
                "Score",
                "Rank",
                "Close",
                "RSI",
                "MACD",
                "ATR",
                "ReferenceShares",
                "ReferenceAmountYen",
                "StopPrice",
                "PositionSizingReason",
            ]:
                if key in signal_df.columns:
                    value = row.get(key)
                    if pd.isna(value):
                        row_data[key] = "-"
                    elif isinstance(value, float):
                        row_data[key] = _format_currency(value) if key in {"Close", "ReferenceAmountYen", "StopPrice"} else str(value)
                    else:
                        row_data[key] = str(value)
                else:
                    row_data[key] = "-"
            rows.append(row_data)

        if "Error" in signal_df.columns:
            errors = [str(item) for item in signal_df["Error"].dropna().tolist() if str(item).strip()]

    if not rows:
        rows = []

    html_rows = []
    for row in rows:
        signal_value = str(row.get("Signal", "HOLD") or "HOLD")
        signal_class = "signal-buy" if signal_value.upper() == "BUY" else "signal-sell" if signal_value.upper() == "SELL" else "signal-hold"
        grade = "A"
        score_value = row.get("Score")
        try:
            score_num = float(score_value)
        except (TypeError, ValueError):
            score_num = 0.0
        if score_num >= 80:
            grade = "A"
        elif score_num >= 60:
            grade = "B"
        elif score_num >= 40:
            grade = "C"
        elif score_num >= 20:
            grade = "D"
        else:
            grade = "E"

        reason_text = str(row.get("PositionSizingReason", "") or "")
        escaped_reason = html.escape(reason_text)
        row_html = [
            f"<tr>",
            f"<td>{html.escape(str(row.get('Ticker', '-')))}</td>",
            f"<td class='{signal_class}'>{html.escape(signal_value)}</td>",
            f"<td>{html.escape(str(score_value))}</td>",
            f"<td>{html.escape(grade)}</td>",
            f"<td>{html.escape(str(row.get('Close', '-')))}</td>",
            f"<td>{html.escape(str(row.get('RSI', '-')))}</td>",
            f"<td>{html.escape(str(row.get('MACD', '-')))}</td>",
            f"<td>{html.escape(str(row.get('ATR', '-')))}</td>",
            f"<td>{html.escape(str(row.get('ReferenceShares', '-')))}</td>",
            f"<td>{html.escape(str(row.get('ReferenceAmountYen', '-')))}</td>",
            f"<td>{html.escape(str(row.get('StopPrice', '-')))}</td>",
            f"<td>{escaped_reason}</td>",
            f"</tr>",
        ]
        html_rows.append("\n".join(row_html))

    score_rows = []
    if rows:
        for row in rows:
            score_value = row.get("Score")
            try:
                score_num = float(score_value)
            except (TypeError, ValueError):
                score_num = 0.0
            score_rows.append((score_num, row))
        score_rows.sort(key=lambda item: item[0], reverse=True)
        ranked_rows = []
        for index, (_, row) in enumerate(score_rows, start=1):
            row["Rank"] = str(index)
            ranked_rows.append(row)
        rows = ranked_rows

    if rows:
        html_rows = []
        for row in rows:
            signal_value = str(row.get("Signal", "HOLD") or "HOLD")
            signal_class = "signal-buy" if signal_value.upper() == "BUY" else "signal-sell" if signal_value.upper() == "SELL" else "signal-hold"

            final_signal_value = str(row.get("FinalSignal", signal_value) or "HOLD")
            final_signal_class = (
                "signal-buy"
                if final_signal_value.upper() == "BUY"
                else "signal-sell"
                if final_signal_value.upper() == "SELL"
                else "signal-hold"
            )
            grade = "A"
            score_value = row.get("Score")
            try:
                score_num = float(score_value)
            except (TypeError, ValueError):
                score_num = 0.0
            if score_num >= 80:
                grade = "A"
            elif score_num >= 60:
                grade = "B"
            elif score_num >= 40:
                grade = "C"
            elif score_num >= 20:
                grade = "D"
            else:
                grade = "E"
            reason_text = str(row.get("PositionSizingReason", "") or "")
            escaped_reason = html.escape(reason_text)
            html_rows.append(
                "\n".join([
                    "<tr>",
                    f"<td>{html.escape(str(row.get('Rank', '-')))}</td>",
                    f"<td>{html.escape(str(row.get('Ticker', '-')))}</td>",
                    f"<td class='{signal_class}'>{html.escape(signal_value)}</td>",
                    f"<td class='{final_signal_class}'>{html.escape(final_signal_value)}</td>",
                    f"<td>{html.escape(str(row.get('AIConfidence', '-')))}</td>",
                    f"<td>{html.escape(str(score_value))}</td>",
                    f"<td>{html.escape(grade)}</td>",
                    f"<td>{html.escape(str(row.get('Close', '-')))}</td>",
                    f"<td>{html.escape(str(row.get('RSI', '-')))}</td>",
                    f"<td>{html.escape(str(row.get('MACD', '-')))}</td>",
                    f"<td>{html.escape(str(row.get('ATR', '-')))}</td>",
                    f"<td>{html.escape(str(row.get('ReferenceShares', '-')))}</td>",
                    f"<td>{html.escape(str(row.get('ReferenceAmountYen', '-')))}</td>",
                    f"<td>{html.escape(str(row.get('StopPrice', '-')))}</td>",
                    f"<td>{escaped_reason}</td>",
                    f"<td>{html.escape(str(row.get('AIReason', '-')))}</td>",
                    f"<td>{html.escape(str(row.get('FinalReason', '-')))}</td>",
                    "</tr>",
                ])
            )

    error_items = "<li>エラー0件</li>" if not errors else "".join(f"<li>{html.escape(str(error))}</li>" for error in errors)
    rows_html = "\n".join(html_rows) if html_rows else "<tr><td colspan='17'>データがありません</td></tr>"
    summary_line = html.escape(summary_text) if summary_text else "-"
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    html_content = f"""<!DOCTYPE html>
<html lang=\"ja\">
<head>
  <meta charset=\"utf-8\">
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">
  <title>stock_v2 ダッシュボード</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 0; padding: 20px; background: #f5f7fb; color: #222; }}
    .card {{ background: white; border-radius: 12px; padding: 16px; box-shadow: 0 2px 8px rgba(0,0,0,0.08); margin-bottom: 16px; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; }}
    .metric {{ background: #f8f9fa; border-radius: 8px; padding: 12px; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 14px; }}
    th, td {{ border: 1px solid #d0d7de; padding: 8px; text-align: left; vertical-align: top; }}
    th {{ background: #eef2ff; }}
    .signal-buy {{ background: #e6ffed; color: #166534; font-weight: 700; }}
    .signal-sell {{ background: #ffeaea; color: #b91c1c; font-weight: 700; }}
    .signal-hold {{ background: #f3f4f6; color: #374151; }}
    .note {{ color: #7c2d12; font-weight: 700; }}
    @media (max-width: 700px) {{ table {{ display:block; overflow-x:auto; white-space:nowrap; }} }}
  </style>
</head>
<body>
  <div class=\"card\">
    <h1>stock_v2 ダッシュボード</h1>
    <p class=\"note\">実注文ではなく参考情報です。</p>
    <p>生成日時: {generated_at}</p>
  </div>
  <div class=\"card\">
    <h2>実行サマリー</h2>
    <div class=\"grid\">
      <div class=\"metric\"><strong>対象銘柄数</strong><br>{len(rows)}</div>
      <div class=\"metric\"><strong>BUY</strong><br>{buy_count}</div>
      <div class=\"metric\"><strong>SELL</strong><br>{sell_count}</div>
      <div class=\"metric\"><strong>HOLD</strong><br>{hold_count}</div>
      <div class=\"metric\"><strong>最高スコア</strong><br>{highest_score:.1f}</div>
      <div class=\"metric\"><strong>平均スコア</strong><br>{average_score:.1f}</div>
      <div class=\"metric\"><strong>参考運用資金</strong><br>{_format_currency(TRADING_CAPITAL)}</div>
      <div class=\"metric\"><strong>サマリー</strong><br>{summary_line}</div>
    </div>
  </div>
  <div class=\"card\">
    <h2>銘柄ランキング</h2>
    <table>
      <thead>
        <tr>
          <th>順位</th>
          <th>Ticker</th>
          <th>テクニカル判定</th>
          <th>AI最終判定</th>
          <th>AI信頼度</th>
          <th>Score</th>
          <th>Rank</th>
          <th>Close</th>
          <th>RSI</th>
          <th>MACD</th>
          <th>ATR</th>
          <th>ReferenceShares</th>
          <th>ReferenceAmountYen</th>
          <th>StopPrice</th>
          <th>PositionSizingReason</th>
          <th>AI判定理由</th>
          <th>最終判定理由</th>
        </tr>
      </thead>
      <tbody>
        {rows_html}
      </tbody>
    </table>
  </div>
  <div class=\"card\">
    <h2>エラー表示</h2>
    <ul>
      {error_items}
    </ul>
  </div>
  <div class=\"card\">
    <p>保存先: results/dashboard.html</p>
  </div>
</body>
</html>
"""

    return html_content


def write_dashboard_html(base_dir: Path | None = None) -> Path:
    base_dir = Path(base_dir or Path("results"))
    base_dir.mkdir(exist_ok=True, parents=True)
    output_path = base_dir / "dashboard.html"
    output_path.write_text(build_dashboard_html(base_dir), encoding="utf-8")
    return output_path


if __name__ == "__main__":
    output_path = write_dashboard_html()
    print(f"ダッシュボードを保存しました: {output_path}")

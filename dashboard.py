from __future__ import annotations

import html
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from config import TRADING_CAPITAL
from ai_asset_platform.reports import (
    append_performance_history,
    calculate_performance,
    calculate_performance_health,
    read_performance_trend,
)
from ai_asset_platform.reports.performance_chart import (
    build_performance_chart_html,
)


def _format_currency(value: Any) -> str:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return "-"
    if numeric == 0:
        return "0"
    return f"{numeric:,.0f}"



def _format_profit_factor(value: Any) -> str:
    """プロフィットファクターを表示用に整える。"""
    numeric_value = float(value)
    if numeric_value == float("inf"):
        return "∞（損失なし）"
    return f"{numeric_value:.2f}"


def _format_signed_number(
    value: Any,
    *,
    decimals: int = 1,
) -> str:
    """増減値をプラス・マイナス記号付きで表示する。"""
    try:
        numeric_value = float(value)
    except (TypeError, ValueError):
        return "-"

    if numeric_value == float("inf"):
        return "+∞"

    if numeric_value == float("-inf"):
        return "-∞"

    return f"{numeric_value:+,.{decimals}f}"


def _performance_status_label(status: str) -> str:
    """英語の推移状態を日本語表示へ変換する。"""
    labels = {
        "improving": "改善",
        "stable": "安定",
        "declining": "悪化",
    }
    return labels.get(status, "不明")

def _performance_health_status_label(status: str) -> str:
    """運用成績の健全度状態を日本語表示へ変換する。"""
    labels = {
        "EXCELLENT": "優秀",
        "GOOD": "良好",
        "CAUTION": "注意",
        "POOR": "不調",
        "NO_DATA": "データ不足",
    }
    return labels.get(status, "不明")


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


def _safe_read_trade_pnls(base_dir: Path) -> list[float]:
    """Paper Tradingの実現損益履歴を安全に読み込む。"""
    path = base_dir / "paper_trade_pnls.json"

    if not path.exists():
        return []

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return []

    if isinstance(data, dict):
        data = data.get("realized_trade_pnls", [])

    if not isinstance(data, list):
        return []

    pnls: list[float] = []
    for value in data:
        try:
            pnls.append(float(value))
        except (TypeError, ValueError):
            continue

    return pnls




def _safe_read_realized_trades(
    base_dir: Path,
) -> list[dict]:
    """Paper Tradingの詳細な確定取引履歴を安全に読み込む。"""

    path = base_dir / "paper_trade_pnls.json"

    if not path.exists():
        return []

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return []

    if not isinstance(data, dict):
        return []

    trades = data.get("realized_trades", [])

    if not isinstance(trades, list):
        return []

    return [
        trade
        for trade in trades
        if isinstance(trade, dict)
    ]


def _safe_read_decision_report(
    base_dir: Path,
) -> dict[str, dict[str, str]]:
    """判断ログ集計CSVを安全に読み込む。"""

    import csv

    path = base_dir / "decision_log_report.csv"

    if not path.exists():
        return {}

    try:
        with path.open(
            "r",
            encoding="utf-8-sig",
            newline="",
        ) as f:
            reader = csv.DictReader(f)

            result: dict[str, dict[str, str]] = {}

            for row in reader:
                category = row.get("Category", "").strip()
                item = row.get("Item", "").strip()
                value = row.get("Value", "").strip()

                if not category or not item:
                    continue

                result.setdefault(category, {})[item] = value

            return result

    except Exception:
        return {}



def calculate_trade_statistics(
    realized_trades: list[dict],
) -> list[dict]:
    """銘柄別の実現損益を集計する。"""

    stats: dict[str, dict] = {}

    for trade in realized_trades:
        ticker = str(trade.get("ticker", "")).strip()
        if not ticker:
            continue

        pnl = float(trade.get("realized_pnl", 0.0))

        item = stats.setdefault(
            ticker,
            {
                "ticker": ticker,
                "total_profit": 0.0,
                "wins": 0,
                "trades": 0,
            },
        )

        item["total_profit"] += pnl
        item["trades"] += 1

        if pnl > 0:
            item["wins"] += 1

    results = []

    for item in stats.values():
        trades = item["trades"]
        item["win_rate"] = (
            item["wins"] / trades * 100
            if trades
            else 0.0
        )
        results.append(item)

    results.sort(
        key=lambda x: x["total_profit"],
        reverse=True,
    )

    return results


def build_dashboard_html(base_dir: Path | None = None) -> str:
    base_dir = Path(base_dir or Path("results"))
    base_dir.mkdir(exist_ok=True, parents=True)

    signal_df = _safe_read_signal_excel(base_dir)
    summary_info = _safe_read_summary_excel(base_dir)
    trade_pnls = _safe_read_trade_pnls(base_dir)
    realized_trades = _safe_read_realized_trades(base_dir)
    trade_statistics = calculate_trade_statistics(realized_trades)
    decision_report = _safe_read_decision_report(base_dir)
    performance = calculate_performance(trade_pnls)
    performance_health = calculate_performance_health(performance)
    performance_trend = read_performance_trend(
        base_dir / "performance_history.csv"
    )
    performance_chart_html = build_performance_chart_html(
        base_dir / "performance_history.csv"
    )

    if performance_trend is None:
        performance_trend_html = """
    <div class="card">
      <h2>運用成績の推移</h2>
      <p>比較できる成績履歴がまだありません。</p>
    </div>
"""
    else:
        performance_trend_html = f"""
    <div class="card">
      <h2>運用成績の推移</h2>
      <div class="grid">
        <div class="metric">
          <strong>総合状態</strong><br>
          {_performance_status_label(performance_trend.status)}
        </div>
        <div class="metric">
          <strong>純損益の変化</strong><br>
          {_format_signed_number(performance_trend.net_profit_change, decimals=0)}円
        </div>
        <div class="metric">
          <strong>勝率の変化</strong><br>
          {_format_signed_number(performance_trend.win_rate_change)}ポイント
        </div>
        <div class="metric">
          <strong>プロフィットファクターの変化</strong><br>
          {_format_signed_number(performance_trend.profit_factor_change, decimals=2)}
        </div>
        <div class="metric">
          <strong>取引数の変化</strong><br>
          {performance_trend.total_trades_change:+d}件
        </div>
      </div>
      <p>
        比較期間:
        {html.escape(performance_trend.previous_recorded_at)}
        ～
        {html.escape(performance_trend.latest_recorded_at)}
      </p>
    </div>
"""

    decision_summary = decision_report.get("Summary", {})
    reason_counts = decision_report.get("Reason", {})
    not_ordered_reason_counts = decision_report.get(
        "NotOrderedReason",
        {},
    )

    total_decisions = decision_summary.get(
        "TotalDecisions",
        "0",
    )
    ordered_count = decision_summary.get(
        "OrderedCount",
        "0",
    )
    not_ordered_count = decision_summary.get(
        "NotOrderedCount",
        "0",
    )
    order_rate = decision_summary.get(
        "OrderRatePercent",
        "0",
    )
    average_ai_confidence = decision_summary.get(
        "AverageAIConfidence",
        "0",
    )

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

    trade_statistics_rows = []

    for rank, item in enumerate(trade_statistics, start=1):
        trade_statistics_rows.append(
            "<tr>"
            f"<td>{rank}</td>"
            f"<td>{html.escape(str(item['ticker']))}</td>"
            f"<td>{int(item['trades'])}</td>"
            f"<td>{int(item['wins'])}</td>"
            f"<td>{float(item['win_rate']):.1f}%</td>"
            f"<td>{_format_currency(item['total_profit'])}</td>"
            "</tr>"
        )

    trade_statistics_html = (
        "\n".join(trade_statistics_rows)
        if trade_statistics_rows
        else "<tr><td colspan='6'>確定取引データがありません</td></tr>"
    )

    error_items = "<li>エラー0件</li>" if not errors else "".join(f"<li>{html.escape(str(error))}</li>" for error in errors)
    rows_html = "\n".join(html_rows) if html_rows else "<tr><td colspan='17'>データがありません</td></tr>"
    summary_line = html.escape(summary_text) if summary_text else "-"
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    reason_items_html = (
        "".join(
            "<li>"
            f"{html.escape(str(reason))}: "
            f"{html.escape(str(count))}件"
            "</li>"
            for reason, count in reason_counts.items()
        )
        if reason_counts
        else "<li>データがありません</li>"
    )

    not_ordered_reason_items_html = (
        "".join(
            "<li>"
            f"{html.escape(str(reason))}: "
            f"{html.escape(str(count))}件"
            "</li>"
            for reason, count in not_ordered_reason_counts.items()
        )
        if not_ordered_reason_counts
        else "<li>注文見送りはありません</li>"
    )

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
    <h2>銘柄別確定損益ランキング</h2>
    <table>
      <thead>
        <tr>
          <th>順位</th>
          <th>銘柄</th>
          <th>取引回数</th>
          <th>勝ち数</th>
          <th>勝率</th>
          <th>合計実現損益</th>
        </tr>
      </thead>
      <tbody>
        {trade_statistics_html}
      </tbody>
    </table>
  </div>
  <div class=\"card\">
    <h2>注文判断ログ集計</h2>
    <div class=\"grid\">
      <div class=\"metric\"><strong>判断件数</strong><br>{html.escape(str(total_decisions))}</div>
      <div class=\"metric\"><strong>注文実行件数</strong><br>{html.escape(str(ordered_count))}</div>
      <div class=\"metric\"><strong>注文未実行件数</strong><br>{html.escape(str(not_ordered_count))}</div>
      <div class=\"metric\"><strong>注文実行率</strong><br>{html.escape(str(order_rate))}%</div>
      <div class=\"metric\"><strong>AI平均信頼度</strong><br>{html.escape(str(average_ai_confidence))}</div>
    </div>
  </div>
  <div class=\"card\">
    <h2>判断理由別集計</h2>
    <div class=\"grid\">
      <div class=\"metric\">
        <strong>すべての判断理由</strong>
        <ul>
          {reason_items_html}
        </ul>
      </div>
      <div class=\"metric\">
        <strong>注文見送り理由</strong>
        <ul>
          {not_ordered_reason_items_html}
        </ul>
      </div>
    </div>
  </div>
  <div class=\"card\">
    <h2>運用成績の健全度</h2>
    <div class=\"grid\">
      <div class=\"metric\"><strong>総合スコア</strong><br>{performance_health.score} / 100</div>
      <div class=\"metric\"><strong>評価</strong><br>{performance_health.grade}</div>
      <div class=\"metric\"><strong>状態</strong><br>{_performance_health_status_label(performance_health.status)}</div>
      <div class=\"metric\"><strong>取引数評価</strong><br>{performance_health.sample_score} / 25</div>
      <div class=\"metric\"><strong>勝率評価</strong><br>{performance_health.win_rate_score} / 25</div>
      <div class=\"metric\"><strong>利益効率評価</strong><br>{performance_health.profit_factor_score} / 25</div>
      <div class=\"metric\"><strong>損益・リスク評価</strong><br>{performance_health.risk_reward_score} / 25</div>
    </div>
    <p>
      取引数、勝率、プロフィットファクター、
      純利益と最大ドローダウンのバランスを総合評価しています。
    </p>
  </div>
  <div class=\"card\">
    <h2>Paper Trading運用成績</h2>
    <div class=\"grid\">
      <div class=\"metric\"><strong>総取引数</strong><br>{performance.total_trades}</div>
      <div class=\"metric\"><strong>勝ち取引</strong><br>{performance.winning_trades}</div>
      <div class=\"metric\"><strong>負け取引</strong><br>{performance.losing_trades}</div>
      <div class=\"metric\"><strong>引き分け</strong><br>{performance.break_even_trades}</div>
      <div class=\"metric\"><strong>勝率</strong><br>{performance.win_rate:.1f}%</div>
      <div class=\"metric\"><strong>純損益</strong><br>{_format_currency(performance.net_profit)}円</div>
      <div class=\"metric\"><strong>総利益</strong><br>{_format_currency(performance.gross_profit)}円</div>
      <div class=\"metric\"><strong>総損失</strong><br>{_format_currency(performance.gross_loss)}円</div>
      <div class=\"metric\"><strong>平均利益</strong><br>{_format_currency(performance.average_profit)}円</div>
      <div class=\"metric\"><strong>平均損失</strong><br>{_format_currency(performance.average_loss)}円</div>
      <div class=\"metric\"><strong>最大利益</strong><br>{_format_currency(performance.largest_profit)}円</div>
      <div class=\"metric\"><strong>最大損失</strong><br>{_format_currency(performance.largest_loss)}円</div>
      <div class=\"metric\"><strong>プロフィットファクター</strong><br>{_format_profit_factor(performance.profit_factor)}</div>
      <div class=\"metric\"><strong>最大連勝数</strong><br>{performance.maximum_winning_streak}回</div>
      <div class=\"metric\"><strong>最大連敗数</strong><br>{performance.maximum_losing_streak}回</div>
      <div class=\"metric\"><strong>最大ドローダウン</strong><br>{_format_currency(performance.maximum_drawdown)}円</div>
    </div>
  </div>
  {performance_trend_html}
  {performance_chart_html}
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

    trade_pnls = _safe_read_trade_pnls(base_dir)
    performance = calculate_performance(trade_pnls)

    append_performance_history(
        performance,
        base_dir / "performance_history.csv",
    )

    output_path = base_dir / "dashboard.html"
    output_path.write_text(
        build_dashboard_html(base_dir),
        encoding="utf-8",
    )
    return output_path


if __name__ == "__main__":
    output_path = write_dashboard_html()
    print(f"ダッシュボードを保存しました: {output_path}")

from __future__ import annotations

import html
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd


DISPLAY_COLUMNS = [
    "Rank",
    "Ticker",
    "Signal",
    "Score",
    "Grade",
    "Close",
    "ATR",
    "StopPrice",
    "ReferenceShares",
    "ReferenceAmountYen",
    "MaxLossYen",
    "PositionSizingReason",
    "Reason",
]


def _format_value(value: Any) -> str:
    if pd.isna(value):
        return "-"
    if isinstance(value, float):
        return f"{value:,.2f}".rstrip("0").rstrip(".")
    return str(value)


def load_candidates(base_dir: Path | None = None) -> pd.DataFrame:
    base_dir = Path(base_dir or "results")
    source = base_dir / "latest_signals.xlsx"
    if not source.exists():
        return pd.DataFrame(columns=DISPLAY_COLUMNS)

    try:
        df = pd.read_excel(source)
    except Exception:
        return pd.DataFrame(columns=DISPLAY_COLUMNS)

    if df.empty or "Signal" not in df.columns:
        return pd.DataFrame(columns=DISPLAY_COLUMNS)

    candidates = df[df["Signal"].astype(str).str.upper().isin(["BUY", "SELL"])].copy()
    if candidates.empty:
        return pd.DataFrame(columns=DISPLAY_COLUMNS)

    if "Score" not in candidates.columns:
        candidates["Score"] = 0
    candidates["Score"] = pd.to_numeric(candidates["Score"], errors="coerce").fillna(0)
    candidates = candidates.sort_values("Score", ascending=False).reset_index(drop=True)
    candidates["Rank"] = range(1, len(candidates) + 1)

    for column in DISPLAY_COLUMNS:
        if column not in candidates.columns:
            candidates[column] = "-"

    return candidates[DISPLAY_COLUMNS]


def build_candidate_dashboard_html(base_dir: Path | None = None) -> str:
    candidates = load_candidates(base_dir)
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if candidates.empty:
        rows_html = f"<tr><td colspan='{len(DISPLAY_COLUMNS)}'>現在、BUY・SELL候補はありません。</td></tr>"
    else:
        rows = []
        for _, row in candidates.iterrows():
            signal = str(row.get("Signal", "-")).upper()
            signal_class = "buy" if signal == "BUY" else "sell"

            try:
                score = float(row.get("Score", 0))
            except (TypeError, ValueError):
                score = 0

            if score >= 80:
                score_class = "score-high"
            elif score >= 60:
                score_class = "score-medium"
            else:
                score_class = "score-low"

            try:
                rank = int(row.get("Rank", 0))
            except (TypeError, ValueError):
                rank = 0

            if rank == 1:
                rank_class = "rank-first"
            elif rank == 2:
                rank_class = "rank-second"
            elif rank == 3:
                rank_class = "rank-third"
            else:
                rank_class = ""

            cells = "".join(
                f"<td>{html.escape(_format_value(row.get(column)))}</td>"
                for column in DISPLAY_COLUMNS
            )
            rows.append(
                f"<tr class='{signal_class} {score_class} {rank_class}'>{cells}</tr>"
            )
        rows_html = "\n".join(rows)

    return f"""<!DOCTYPE html>
<html lang='ja'>
<head>
  <meta charset='utf-8'>
  <meta name='viewport' content='width=device-width, initial-scale=1'>
  <title>BUY・SELL候補一覧</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 0; padding: 20px; background: #f5f7fb; color: #222; }}
    .card {{ background: #fff; border-radius: 12px; padding: 16px; box-shadow: 0 2px 8px rgba(0,0,0,.08); }}
    table {{ width: 100%; border-collapse: collapse; margin-top: 14px; }}
    th, td {{ border: 1px solid #d0d7de; padding: 9px; text-align: left; }}
    th {{ background: #eef2ff; }}
    tr.buy td {{ background: #e6ffed; }}
    tr.sell td {{ background: #ffeaea; }}
    tr.score-high td {{ font-weight: 700; border-top: 3px solid #f59e0b; border-bottom: 3px solid #f59e0b; }}
    tr.score-medium td {{ font-weight: 600; }}
    tr.score-low td {{ opacity: .82; }}
    tr:hover td {{ filter: brightness(.97); }}
    tr.rank-first td {{
      background: linear-gradient(90deg,#fff8dc,#ffe082);
    }}
    tr.rank-second td {{
      background: linear-gradient(90deg,#f5f5f5,#d9d9d9);
    }}
    tr.rank-third td {{
      background: linear-gradient(90deg,#fff3e0,#d7a86e);
    }}
    tr.rank-first td {{
      background: linear-gradient(90deg, #fff8dc, #ffe082);
    }}
    tr.rank-second td {{
      background: linear-gradient(90deg, #f5f5f5, #d9d9d9);
    }}
    tr.rank-third td {{
      background: linear-gradient(90deg, #fff3e0, #d7a86e);
    }}
    .note {{ color: #7c2d12; font-weight: 700; }}
    @media (max-width: 700px) {{ table {{ display: block; overflow-x: auto; white-space: nowrap; }} }}
  </style>
</head>
<body>
  <div class='card'>
    <h1>BUY・SELL候補一覧</h1>
    <p class='note'>HOLD銘柄は除外しています。実注文ではなく参考情報です。</p>
    <p>生成日時: {generated_at}</p>
    <table>
      <thead>
        <tr>
          <th>順位</th>
          <th>銘柄コード</th>
          <th>売買判断</th>
          <th>スコア</th>
          <th>評価</th>
          <th>現在価格</th>
          <th>ATR</th>
          <th>損切価格</th>
          <th>参考株数</th>
          <th>参考金額</th>
          <th>最大損失額</th>
          <th>株数の計算理由</th>
          <th>売買判断の理由</th>
        </tr>
      </thead>
      <tbody>{rows_html}</tbody>
    </table>
  </div>
</body>
</html>
"""


def write_candidate_dashboard(base_dir: Path | None = None) -> Path:
    base_dir = Path(base_dir or "results")
    base_dir.mkdir(parents=True, exist_ok=True)
    output = base_dir / "candidate_dashboard.html"
    output.write_text(build_candidate_dashboard_html(base_dir), encoding="utf-8")
    return output


if __name__ == "__main__":
    path = write_candidate_dashboard()
    print(f"BUY・SELL候補ダッシュボードを保存しました: {path}")

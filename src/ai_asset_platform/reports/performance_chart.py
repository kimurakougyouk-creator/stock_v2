from __future__ import annotations

import csv
import html
from pathlib import Path


def build_performance_chart_html(
    history_path: Path,
) -> str:
    """運用成績履歴から純損益グラフを生成する。"""
    rows = _read_history(history_path)

    if len(rows) < 2:
        return (
            '<div class="card">'
            "<h2>運用成績グラフ</h2>"
            "<p>グラフ表示に必要な成績履歴がまだありません。</p>"
            "</div>"
        )

    rows = rows[-20:]
    values = [float(row["net_profit"]) for row in rows]

    width = 800
    height = 280
    left = 70
    right = 30
    top = 25
    bottom = 50

    minimum = min(values)
    maximum = max(values)

    if minimum == maximum:
        margin = max(abs(minimum) * 0.1, 1.0)
        minimum -= margin
        maximum += margin

    chart_width = width - left - right
    chart_height = height - top - bottom
    value_range = maximum - minimum

    def x(index: int) -> float:
        return left + chart_width * index / (len(values) - 1)

    def y(value: float) -> float:
        return top + (maximum - value) / value_range * chart_height

    points = " ".join(
        f"{x(index):.1f},{y(value):.1f}"
        for index, value in enumerate(values)
    )

    first_date = html.escape(str(rows[0]["recorded_at"]))
    latest_date = html.escape(str(rows[-1]["recorded_at"]))
    latest_profit = values[-1]

    return f"""
<div class="card">
  <h2>運用成績グラフ</h2>
  <p>純損益の推移（直近{len(rows)}件）</p>
  <div style="overflow-x:auto;">
    <svg
      viewBox="0 0 {width} {height}"
      role="img"
      aria-label="純損益の推移グラフ"
      style="width:100%;min-width:600px;height:auto;"
    >
      <rect
        x="{left}" y="{top}"
        width="{chart_width}" height="{chart_height}"
        fill="#f8f9fa" stroke="#d0d7de"
      />
      <polyline
        points="{points}"
        fill="none"
        stroke="#2563eb"
        stroke-width="4"
        stroke-linejoin="round"
        stroke-linecap="round"
      />
      <text x="10" y="{top + 5}" font-size="14">
        {maximum:,.0f}円
      </text>
      <text x="10" y="{height - bottom + 5}" font-size="14">
        {minimum:,.0f}円
      </text>
      <text x="{left}" y="{height - 15}" font-size="13">
        {first_date}
      </text>
      <text
        x="{width - right}"
        y="{height - 15}"
        text-anchor="end"
        font-size="13"
      >
        {latest_date}
      </text>
    </svg>
  </div>
  <p><strong>最新の純損益:</strong> {latest_profit:,.0f}円</p>
</div>
"""


def _read_history(
    history_path: Path,
) -> list[dict[str, str]]:
    if not history_path.exists():
        return []

    try:
        with history_path.open(
            "r",
            encoding="utf-8-sig",
            newline="",
        ) as file:
            rows = list(csv.DictReader(file))
    except (OSError, csv.Error):
        return []

    valid_rows: list[dict[str, str]] = []

    for row in rows:
        try:
            float(row.get("net_profit", ""))
        except (TypeError, ValueError):
            continue

        if not str(row.get("recorded_at", "")).strip():
            continue

        valid_rows.append(row)

    return valid_rows

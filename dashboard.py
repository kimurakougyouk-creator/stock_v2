from __future__ import annotations

import json
from pathlib import Path

import dashboard_core as _core
from dashboard_core import *  # noqa: F401,F403
from config import TRADING_CAPITAL
from ai_asset_platform.reports.equity_chart import build_equity_chart_html
from ai_asset_platform.reports.equity_history import (
    append_equity_history,
    calculate_equity_curve,
    calculate_maximum_drawdown,
)


def _safe_read_paper_orders(base_dir: Path) -> list[dict]:
    path = base_dir / "paper_orders.jsonl"
    if not path.exists():
        return []
    orders = []
    try:
        with path.open("r", encoding="utf-8") as file:
            for line in file:
                line = line.strip()
                if not line:
                    continue
                try:
                    order = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(order, dict):
                    orders.append(order)
    except OSError:
        return []
    return orders


def _equity_card(base_dir: Path) -> str:
    points = calculate_equity_curve(
        _safe_read_paper_orders(base_dir),
        initial_capital=float(TRADING_CAPITAL),
    )
    latest = points[-1].total_assets if points else float(TRADING_CAPITAL)
    drawdown = calculate_maximum_drawdown(points)
    chart = build_equity_chart_html(base_dir / "equity_history.csv")
    return f"""
<div class="card">
  <h2>総資産（Equity）</h2>
  <div class="grid">
    <div class="metric"><strong>最新総資産</strong><br>{latest:,.0f}円</div>
    <div class="metric"><strong>総資産ベース最大Drawdown</strong><br>{drawdown:,.0f}円</div>
  </div>
</div>
{chart}
"""


def build_dashboard_html(base_dir: Path | None = None) -> str:
    base_dir = Path(base_dir or Path("results"))
    original = _core.build_dashboard_html(base_dir)
    return original.replace("</body>", _equity_card(base_dir) + "\n</body>", 1)


def write_dashboard_html(base_dir: Path | None = None) -> Path:
    base_dir = Path(base_dir or Path("results"))
    base_dir.mkdir(exist_ok=True, parents=True)
    trade_pnls = _core._safe_read_trade_pnls(base_dir)
    performance = _core.calculate_performance(trade_pnls)
    _core.append_performance_history(performance, base_dir / "performance_history.csv")
    points = calculate_equity_curve(
        _safe_read_paper_orders(base_dir),
        initial_capital=float(TRADING_CAPITAL),
    )
    if points:
        append_equity_history(points[-1], base_dir / "equity_history.csv")
    output_path = base_dir / "dashboard.html"
    output_path.write_text(build_dashboard_html(base_dir), encoding="utf-8")
    return output_path


if __name__ == "__main__":
    output_path = write_dashboard_html()
    print(f"ダッシュボードを保存しました: {output_path}")

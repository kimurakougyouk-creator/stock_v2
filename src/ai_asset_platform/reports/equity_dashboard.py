"""Dashboard-safe total-asset equity summary."""

from __future__ import annotations

from pathlib import Path

from ai_asset_platform.reports.equity_history import (
    calculate_equity_curve,
    calculate_maximum_drawdown,
    load_equity_history,
)


def build_equity_summary_html(path: str | Path) -> str:
    points = load_equity_history(path)
    if not points:
        return """
    <div class="card">
      <h2>総資産 Equity Curve</h2>
      <p>Equity履歴がまだありません。</p>
    </div>
"""
    curve = calculate_equity_curve(points)
    latest = curve[-1]
    drawdown = calculate_maximum_drawdown(curve)
    return f"""
    <div class="card">
      <h2>総資産 Equity Curve</h2>
      <div class="grid">
        <div class="metric"><strong>最新総資産</strong><br>{latest:,.0f}円</div>
        <div class="metric"><strong>総資産最大Drawdown</strong><br>{drawdown:,.0f}円</div>
        <div class="metric"><strong>記録点数</strong><br>{len(curve)}</div>
      </div>
    </div>
"""

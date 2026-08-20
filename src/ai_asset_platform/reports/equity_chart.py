"""Equity-curve chart generation from total assets."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

import matplotlib.pyplot as plt

from ai_asset_platform.reports.equity_history import EquityPoint


def save_equity_chart(points: Iterable[EquityPoint], output_path: str | Path) -> Path:
    history = list(points)
    if not history:
        raise ValueError("equity history is empty")

    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)

    figure, axis = plt.subplots()
    axis.plot(range(len(history)), [point.total_assets for point in history])
    axis.set_title("Equity Curve")
    axis.set_xlabel("Fill")
    axis.set_ylabel("Total Assets")
    axis.grid(True)
    figure.tight_layout()
    figure.savefig(target)
    plt.close(figure)
    return target

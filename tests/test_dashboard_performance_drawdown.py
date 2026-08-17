from __future__ import annotations

import json
from pathlib import Path

from dashboard import build_dashboard_html


def test_dashboard_displays_maximum_drawdown(
    tmp_path: Path,
) -> None:
    data = {
        "realized_trade_pnls": [
            1000.0,
            500.0,
            -300.0,
            -200.0,
            -100.0,
            400.0,
        ]
    }

    (tmp_path / "paper_trade_pnls.json").write_text(
        json.dumps(data),
        encoding="utf-8",
    )

    result = build_dashboard_html(tmp_path)

    assert "最大ドローダウン" in result
    assert "600円" in result

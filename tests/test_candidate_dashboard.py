from pathlib import Path

import pandas as pd

from candidate_dashboard import build_candidate_dashboard_html, load_candidates, write_candidate_dashboard


def test_load_candidates_filters_hold_and_sorts(tmp_path: Path) -> None:
    results = tmp_path / "results"
    results.mkdir()
    pd.DataFrame(
        [
            {"Ticker": "AAA", "Signal": "HOLD", "Score": 90, "Close": 100, "ATR": 2, "StopPrice": 95},
            {"Ticker": "BBB", "Signal": "BUY", "Score": 70, "Close": 200, "ATR": 3, "StopPrice": 190},
            {"Ticker": "CCC", "Signal": "SELL", "Score": 80, "Close": 300, "ATR": 4, "StopPrice": 310},
        ]
    ).to_excel(results / "latest_signals.xlsx", index=False)

    candidates = load_candidates(results)

    assert candidates["Ticker"].tolist() == ["CCC", "BBB"]
    assert candidates["Rank"].tolist() == [1, 2]
    assert "AAA" not in candidates["Ticker"].tolist()


def test_build_dashboard_shows_empty_message(tmp_path: Path) -> None:
    html = build_candidate_dashboard_html(tmp_path / "results")
    assert "現在、BUY・SELL候補はありません。" in html


def test_write_candidate_dashboard(tmp_path: Path) -> None:
    results = tmp_path / "results"
    output = write_candidate_dashboard(results)
    assert output.exists()
    assert output.name == "candidate_dashboard.html"

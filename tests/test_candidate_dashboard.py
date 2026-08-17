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


def test_load_candidates_uses_final_signal_and_shows_ai_fields(tmp_path: Path) -> None:
    results = tmp_path / "results"
    results.mkdir()

    pd.DataFrame(
        [
            {
                "Ticker": "AAA",
                "Signal": "BUY",
                "FinalSignal": "HOLD",
                "AIConfidence": 95,
                "AIReason": "AIは見送り",
                "FinalReason": "テクニカルとAIが不一致",
                "Score": 90,
            },
            {
                "Ticker": "BBB",
                "Signal": "BUY",
                "FinalSignal": "BUY",
                "AIConfidence": 88,
                "AIReason": "上昇余地あり",
                "FinalReason": "テクニカルとAIが一致",
                "Score": 80,
            },
            {
                "Ticker": "CCC",
                "Signal": "HOLD",
                "FinalSignal": "SELL",
                "AIConfidence": 82,
                "AIReason": "下落リスクが高い",
                "FinalReason": "AI最終判定はSELL",
                "Score": 70,
            },
        ]
    ).to_excel(results / "latest_signals.xlsx", index=False)

    candidates = load_candidates(results)

    assert candidates["Ticker"].tolist() == ["BBB", "CCC"]
    assert candidates["FinalSignal"].tolist() == ["BUY", "SELL"]
    assert candidates["AIConfidence"].tolist() == [88, 82]

    html = build_candidate_dashboard_html(results)

    assert "AI最終" in html
    assert "AI信頼度" in html
    assert "上昇余地あり" in html
    assert "テクニカルとAIが一致" in html
    assert "AIは見送り" not in html

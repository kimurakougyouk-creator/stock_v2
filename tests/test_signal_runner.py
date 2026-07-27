from pathlib import Path

import pandas as pd

from signal_runner import run_signal_scan
from dashboard import build_dashboard_html


def test_run_signal_scan_creates_excel_report(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "tickers.csv").write_text("Ticker\n7203.T\n", encoding="utf-8")

    class FakeYFinance:
        def __call__(self, ticker, period, interval, auto_adjust):
            return pd.DataFrame([
                {
                    "Close": 110.0,
                    "High": 112.0,
                    "Low": 108.0,
                    "Volume": 1000.0,
                }
            ])

    monkeypatch.setattr("signal_runner.yf.download", FakeYFinance())
    monkeypatch.setattr("signal_runner.send_mail", lambda *args, **kwargs: None)

    result = run_signal_scan(["7203.T"])

    assert Path(result["output_path"]).exists()
    assert result["records"][0]["Signal"] in {"BUY", "SELL", "HOLD"}


def test_run_signal_scan_writes_score_columns_and_sorts_by_score(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "tickers.csv").write_text("Ticker\n7203.T\n7204.T\n", encoding="utf-8")

    class FakeYFinance:
        def __call__(self, ticker, period, interval, auto_adjust):
            if ticker == "7203.T":
                return pd.DataFrame([
                    {
                        "Close": 120.0,
                        "High": 122.0,
                        "Low": 118.0,
                        "Volume": 2_000.0,
                    }
                ])
            return pd.DataFrame([
                {
                    "Close": 80.0,
                    "High": 82.0,
                    "Low": 78.0,
                    "Volume": 500.0,
                }
            ])

    monkeypatch.setattr("signal_runner.yf.download", FakeYFinance())
    monkeypatch.setattr("signal_runner.send_mail", lambda *args, **kwargs: None)

    result = run_signal_scan(["7203.T", "7204.T"])

    output_path = Path(result["output_path"])
    output_df = pd.read_excel(output_path)

    assert {"Score", "Rank", "StopPrice", "RiskPerShare", "MaxLossYen", "ReferenceShares", "ReferenceAmountYen", "PositionSizingReason"}.issubset(output_df.columns)
    assert output_df["Score"].tolist() == sorted(output_df["Score"].tolist(), reverse=True)
    assert output_df.iloc[0]["Ticker"] == "7203.T"


def test_build_dashboard_html_generates_safe_report(tmp_path):
    signal_path = tmp_path / "latest_signals.xlsx"
    signal_df = pd.DataFrame([
        {
            "Ticker": "7203.T",
            "Signal": "BUY",
            "Score": 92.0,
            "Rank": 1,
            "Close": 1000.0,
            "RSI": 70.0,
            "MACD": 1.5,
            "ATR": 10.0,
            "ReferenceShares": 100,
            "ReferenceAmountYen": 100000.0,
            "StopPrice": 970.0,
            "PositionSizingReason": "テスト用理由 <script>alert(1)</script>",
        },
        {
            "Ticker": "7204.T",
            "Signal": "HOLD",
            "Score": 40.0,
            "Rank": 2,
            "Close": 500.0,
            "RSI": 50.0,
            "MACD": 0.0,
            "ATR": 5.0,
            "ReferenceShares": 0,
            "ReferenceAmountYen": 0.0,
            "StopPrice": 500.0,
            "PositionSizingReason": "",
        },
    ])
    signal_df.to_excel(signal_path, index=False)

    html = build_dashboard_html(tmp_path)

    assert "results/dashboard.html" in html
    assert "BUY" in html and "HOLD" in html
    assert "92" in html and "40" in html
    assert "1,000" in html or "1000" in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "実注文ではなく参考情報" in html
    assert "秘密情報" not in html


def test_run_signal_scan_writes_ai_judgement_columns(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "tickers.csv").write_text(
        "Ticker\n7203.T\n",
        encoding="utf-8",
    )

    class FakeYFinance:
        def __call__(self, ticker, period, interval, auto_adjust):
            return pd.DataFrame([
                {
                    "Close": 110.0,
                    "High": 112.0,
                    "Low": 108.0,
                    "Volume": 1000.0,
                }
            ])

    class FakeAIProvider:
        name = "openai"

        def evaluate(self, market_data):
            assert market_data["ticker"] == "7203.T"
            assert market_data["technical_signal"] in {
                "BUY",
                "SELL",
                "HOLD",
            }

            return {
                "signal": "BUY",
                "score": 88,
                "confidence": 91,
                "reason": "AIテスト判定です。",
            }

    monkeypatch.setattr(
        "signal_runner.yf.download",
        FakeYFinance(),
    )
    monkeypatch.setattr(
        "signal_runner.send_mail",
        lambda *args, **kwargs: None,
    )

    result = run_signal_scan(
        ["7203.T"],
        ai_provider=FakeAIProvider(),
    )

    output_df = pd.read_excel(result["output_path"])

    expected_columns = {
        "AISignal",
        "AIScore",
        "AIConfidence",
        "AIReason",
        "AIProvider",
        "AIAvailable",
    }

    assert expected_columns.issubset(output_df.columns)
    assert output_df.iloc[0]["AISignal"] == "BUY"
    assert output_df.iloc[0]["AIScore"] == 88
    assert output_df.iloc[0]["AIConfidence"] == 91
    assert output_df.iloc[0]["AIProvider"] == "openai"
    assert bool(output_df.iloc[0]["AIAvailable"]) is True

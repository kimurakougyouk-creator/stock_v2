from pathlib import Path

import pandas as pd

from signal_runner import run_signal_scan


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

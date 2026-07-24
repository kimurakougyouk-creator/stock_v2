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

from pathlib import Path

import pandas as pd

from change_tracker import update_change_tracking


def test_first_run_creates_baseline_without_email(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    current_df = pd.DataFrame([
        {"Ticker": "7203.T", "Signal": "BUY", "Score": 90.0, "Rank": 1, "Close": 1000.0}
    ])

    sent = []

    result = update_change_tracking(current_df, base_dir=tmp_path, send_mail_fn=lambda *args, **kwargs: sent.append((args, kwargs)))

    assert result["is_first_run"] is True
    assert result["important_change_count"] == 0
    assert (tmp_path / "previous_signals.xlsx").exists()
    assert (tmp_path / "latest_changes.xlsx").exists()
    assert (tmp_path / "history").exists()
    assert sent == []


def test_detects_signal_change_as_important(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    previous_df = pd.DataFrame([
        {"Ticker": "7203.T", "Signal": "BUY", "Score": 80.0, "Rank": 1, "Close": 1000.0}
    ])
    current_df = pd.DataFrame([
        {"Ticker": "7203.T", "Signal": "SELL", "Score": 80.0, "Rank": 1, "Close": 1000.0}
    ])
    previous_path = tmp_path / "previous_signals.xlsx"
    previous_df.to_excel(previous_path, index=False)

    result = update_change_tracking(current_df, base_dir=tmp_path)

    assert result["important_change_count"] == 1
    assert result["important_changes"][0]["ChangeType"] == "SignalChange"
    assert result["important_changes"][0]["IsImportant"] is True


def test_detects_score_threshold_as_important(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    previous_df = pd.DataFrame([
        {"Ticker": "7203.T", "Signal": "BUY", "Score": 60.0, "Rank": 1, "Close": 1000.0}
    ])
    current_df = pd.DataFrame([
        {"Ticker": "7203.T", "Signal": "BUY", "Score": 80.0, "Rank": 1, "Close": 1000.0}
    ])
    previous_path = tmp_path / "previous_signals.xlsx"
    previous_df.to_excel(previous_path, index=False)

    result = update_change_tracking(current_df, base_dir=tmp_path)

    assert result["important_change_count"] == 1
    assert result["important_changes"][0]["ScoreChange"] >= 15


def test_ignores_small_score_change(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    previous_df = pd.DataFrame([
        {"Ticker": "7203.T", "Signal": "BUY", "Score": 60.0, "Rank": 1, "Close": 1000.0}
    ])
    current_df = pd.DataFrame([
        {"Ticker": "7203.T", "Signal": "BUY", "Score": 74.0, "Rank": 1, "Close": 1000.0}
    ])
    previous_path = tmp_path / "previous_signals.xlsx"
    previous_df.to_excel(previous_path, index=False)

    result = update_change_tracking(current_df, base_dir=tmp_path)

    assert result["important_change_count"] == 0


def test_skips_duplicate_history_for_same_content(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    current_df = pd.DataFrame([
        {"Ticker": "7203.T", "Signal": "BUY", "Score": 90.0, "Rank": 1, "Close": 1000.0}
    ])

    first = update_change_tracking(current_df, base_dir=tmp_path)
    second = update_change_tracking(current_df, base_dir=tmp_path)

    history_files = list((tmp_path / "history").glob("signals_*.xlsx"))
    assert len(history_files) == 1
    assert first["history_created"] is True
    assert second["history_created"] is False


def test_handles_missing_columns_and_nan_without_stopping(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    previous_df = pd.DataFrame([
        {"Ticker": "7203.T", "Signal": "BUY", "Score": 60.0, "Rank": 1, "Close": 1000.0}
    ])
    current_df = pd.DataFrame([
        {"Ticker": "7204.T", "Signal": "HOLD", "Score": float("nan"), "Rank": 2, "Close": float("nan")}
    ])
    previous_path = tmp_path / "previous_signals.xlsx"
    previous_df.to_excel(previous_path, index=False)

    result = update_change_tracking(current_df, base_dir=tmp_path)

    assert result["important_change_count"] >= 0
    assert (tmp_path / "latest_changes.xlsx").exists()

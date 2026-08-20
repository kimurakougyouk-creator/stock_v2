import pytest

from ai_asset_platform.execution.paper_trading_loop import (
    run_paper_trading_loop,
)


def test_loop_completes_all_normal_runs():
    calls = []

    def run_once():
        calls.append(1)
        return {"records": [{"Ticker": "7203.T"}], "errors": []}

    result = run_paper_trading_loop(run_once=run_once, max_runs=3)
    assert result.completed_runs == 3
    assert result.stopped_early is False
    assert result.last_health.status == "NORMAL"
    assert len(calls) == 3


def test_loop_stops_immediately_on_error():
    results = [
        {"records": [{"Ticker": "7203.T"}], "errors": []},
        {"records": [], "errors": ["download error"]},
        {"records": [{"Ticker": "6758.T"}], "errors": []},
    ]
    calls = []

    def run_once():
        calls.append(1)
        return results[len(calls) - 1]

    result = run_paper_trading_loop(run_once=run_once, max_runs=3)
    assert result.completed_runs == 2
    assert result.stopped_early is True
    assert result.last_health.status == "ERROR"
    assert len(calls) == 2


def test_loop_allows_warning_and_continues():
    calls = []

    def run_once():
        calls.append(1)
        return {"records": [], "errors": []}

    result = run_paper_trading_loop(run_once=run_once, max_runs=2)
    assert result.completed_runs == 2
    assert result.stopped_early is False
    assert result.last_health.status == "WARNING"


def test_loop_rejects_invalid_max_runs():
    with pytest.raises(ValueError, match="max_runsは1以上"):
        run_paper_trading_loop(run_once=lambda: {"records": [], "errors": []}, max_runs=0)


def test_loop_waits_only_between_runs():
    sleeps = []
    result = run_paper_trading_loop(
        run_once=lambda: {"records": [{"Ticker": "7203.T"}], "errors": []},
        max_runs=3,
        interval_seconds=60,
        sleep_fn=sleeps.append,
    )
    assert result.completed_runs == 3
    assert sleeps == [60.0, 60.0]


def test_loop_does_not_wait_after_error():
    sleeps = []
    results = [
        {"records": [{"Ticker": "7203.T"}], "errors": []},
        {"records": [], "errors": ["gateway disconnected"]},
    ]
    calls = []

    def run_once():
        value = results[len(calls)]
        calls.append(1)
        return value

    result = run_paper_trading_loop(
        run_once=run_once,
        max_runs=3,
        interval_seconds=60,
        sleep_fn=sleeps.append,
    )
    assert result.stopped_early is True
    assert sleeps == [60.0]


def test_loop_rejects_negative_interval():
    with pytest.raises(ValueError, match="interval_secondsは0以上"):
        run_paper_trading_loop(
            run_once=lambda: {"records": [], "errors": []},
            max_runs=1,
            interval_seconds=-1,
        )

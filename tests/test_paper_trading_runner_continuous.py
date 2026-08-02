from types import SimpleNamespace

import paper_trading_runner


def test_continuous_runner_connects_to_safe_loop(monkeypatch):
    calls = []

    monkeypatch.setattr(
        paper_trading_runner,
        "run_paper_trading",
        lambda: {
            "records": [{"Ticker": "7203.T"}],
            "errors": [],
        },
    )

    result = paper_trading_runner.run_continuous_paper_trading(
        max_runs=3,
    )

    assert result.completed_runs == 3
    assert result.stopped_early is False
    assert result.last_health.status == "NORMAL"


def test_continuous_runner_stops_on_error(monkeypatch):
    results = [
        {
            "records": [{"Ticker": "7203.T"}],
            "errors": [],
        },
        {
            "records": [],
            "errors": ["test error"],
        },
        {
            "records": [{"Ticker": "6758.T"}],
            "errors": [],
        },
    ]

    calls = []

    def fake_run():
        calls.append(1)
        return results[len(calls) - 1]

    monkeypatch.setattr(
        paper_trading_runner,
        "run_paper_trading",
        fake_run,
    )

    result = paper_trading_runner.run_continuous_paper_trading(
        max_runs=3,
    )

    assert result.completed_runs == 2
    assert result.stopped_early is True
    assert result.last_health.status == "ERROR"
    assert len(calls) == 2

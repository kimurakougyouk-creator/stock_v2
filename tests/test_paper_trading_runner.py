from types import SimpleNamespace

import pytest

import paper_trading_runner


def test_paper_runner_enables_orders_only_for_paper(monkeypatch):
    calls = []

    monkeypatch.setattr(
        paper_trading_runner,
        "SETTINGS",
        SimpleNamespace(
            enable_paper_trading=True,
            live_trading_unlocked=False,
        ),
    )
    monkeypatch.setattr(
        paper_trading_runner,
        "_create_configured_ai_provider",
        lambda: "TEST_AI",
    )
    monkeypatch.setattr(
        paper_trading_runner,
        "run_signal_scan",
        lambda **kwargs: calls.append(kwargs)
        or {
            "records": [],
            "errors": [],
        },
    )

    result = paper_trading_runner.run_paper_trading()

    assert result == {
        "records": [],
        "errors": [],
    }

    assert calls == [
        {
            "ai_provider": "TEST_AI",
            "allow_orders": True,
            "allow_email": False,
        }
    ]


def test_paper_runner_rejects_disabled_paper(monkeypatch):
    monkeypatch.setattr(
        paper_trading_runner,
        "SETTINGS",
        SimpleNamespace(
            enable_paper_trading=False,
            live_trading_unlocked=False,
        ),
    )

    with pytest.raises(RuntimeError, match="Paper Tradingが無効"):
        paper_trading_runner.run_paper_trading()


def test_paper_runner_rejects_live_unlocked(monkeypatch):
    monkeypatch.setattr(
        paper_trading_runner,
        "SETTINGS",
        SimpleNamespace(
            enable_paper_trading=True,
            live_trading_unlocked=True,
        ),
    )

    with pytest.raises(RuntimeError, match="Live Trading"):
        paper_trading_runner.run_paper_trading()


def test_paper_runner_main_prints_normal_health(monkeypatch, capsys):
    monkeypatch.setattr(
        paper_trading_runner,
        "run_paper_trading",
        lambda: {
            "records": [{} for _ in range(10)],
            "errors": [],
        },
    )

    paper_trading_runner.main()

    output = capsys.readouterr().out

    assert "診断結果    : NORMAL" in output
    assert "Paper Tradingは正常です。" in output
    assert "シグナル件数: 10" in output
    assert "エラー件数  : 0" in output


def test_paper_runner_main_prints_error_health(monkeypatch, capsys):
    monkeypatch.setattr(
        paper_trading_runner,
        "run_paper_trading",
        lambda: {
            "records": [{} for _ in range(9)],
            "errors": ["download error"],
        },
    )

    paper_trading_runner.main()

    output = capsys.readouterr().out

    assert "診断結果    : ERROR" in output
    assert "1件のエラーが発生しました。" in output
    assert "シグナル件数: 9" in output
    assert "エラー件数  : 1" in output

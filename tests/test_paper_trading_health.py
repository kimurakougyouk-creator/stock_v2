import pytest

from ai_asset_platform.reports.paper_trading_health import (
    evaluate_paper_trading_health,
)


def test_paper_trading_health_normal():
    result = evaluate_paper_trading_health(
        signal_count=10,
        error_count=0,
    )

    assert result.status == "NORMAL"
    assert result.signal_count == 10
    assert result.error_count == 0
    assert result.message == "Paper Tradingは正常です。"


def test_paper_trading_health_warning_when_no_signals():
    result = evaluate_paper_trading_health(
        signal_count=0,
        error_count=0,
    )

    assert result.status == "WARNING"
    assert result.signal_count == 0
    assert result.error_count == 0


def test_paper_trading_health_error():
    result = evaluate_paper_trading_health(
        signal_count=9,
        error_count=1,
    )

    assert result.status == "ERROR"
    assert result.signal_count == 9
    assert result.error_count == 1


@pytest.mark.parametrize(
    ("signal_count", "error_count"),
    [
        (-1, 0),
        (10, -1),
    ],
)
def test_paper_trading_health_rejects_negative_counts(
    signal_count,
    error_count,
):
    with pytest.raises(ValueError):
        evaluate_paper_trading_health(
            signal_count=signal_count,
            error_count=error_count,
        )

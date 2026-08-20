from ai_asset_platform.reports.equity_chart import save_equity_chart
from ai_asset_platform.reports.equity_history import EquityPoint


def test_save_equity_chart_uses_total_asset_history(tmp_path):
    output = tmp_path / "equity.png"
    result = save_equity_chart(
        [
            EquityPoint("t1", "a", 900, 100, 1000),
            EquityPoint("t2", "b", 800, 250, 1050),
        ],
        output,
    )
    assert result == output
    assert output.exists()
    assert output.stat().st_size > 0


def test_save_equity_chart_rejects_empty_history(tmp_path):
    try:
        save_equity_chart([], tmp_path / "equity.png")
    except ValueError as exc:
        assert "empty" in str(exc)
    else:
        raise AssertionError("ValueError was not raised")

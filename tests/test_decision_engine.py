import pytest

from ai_asset_platform.decision_engine import combine_decisions


def test_uses_technical_result_when_ai_result_is_missing():
    result = combine_decisions(
        {
            "signal": "BUY",
            "score": 85,
            "reason": "上昇トレンドです。",
        }
    )

    assert result.signal == "BUY"
    assert result.score == 85
    assert result.ai_signal is None
    assert "AI評価なし" in result.reason


def test_combines_matching_buy_decisions():
    result = combine_decisions(
        {
            "signal": "BUY",
            "score": 90,
            "reason": "テクニカルは強気です。",
        },
        {
            "signal": "BUY",
            "score": 80,
            "reason": "AIも強気です。",
        },
    )

    assert result.signal == "BUY"
    assert result.score > 50
    assert result.confidence > 0
    assert result.technical_signal == "BUY"
    assert result.ai_signal == "BUY"


def test_returns_hold_when_technical_and_ai_conflict():
    result = combine_decisions(
        {
            "signal": "BUY",
            "score": 80,
            "reason": "テクニカルは買いです。",
        },
        {
            "signal": "SELL",
            "score": 100,
            "reason": "AIは売りです。",
        },
        technical_weight=0.5,
        ai_weight=0.5,
    )

    assert result.signal == "HOLD"


def test_combines_matching_sell_decisions():
    result = combine_decisions(
        {
            "signal": "SELL",
            "score": 10,
            "reason": "下降トレンドです。",
        },
        {
            "signal": "SELL",
            "score": 20,
            "reason": "AIも弱気です。",
        },
    )

    assert result.signal == "SELL"
    assert result.score < 50


def test_invalid_signals_are_safely_changed_to_hold():
    result = combine_decisions(
        {
            "signal": "UNKNOWN",
            "score": 50,
            "reason": "不明です。",
        }
    )

    assert result.signal == "HOLD"
    assert result.technical_signal == "HOLD"


def test_rejects_negative_weights():
    with pytest.raises(ValueError):
        combine_decisions(
            {"signal": "BUY", "score": 80},
            {"signal": "BUY", "score": 80},
            technical_weight=-1,
        )

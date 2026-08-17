from ai_asset_platform.ai import AIJudgeResult
from ai_asset_platform.decision import determine_final_decision


def create_ai_result(
    *,
    signal: str,
    confidence: float = 80.0,
    available: bool = True,
) -> AIJudgeResult:
    return AIJudgeResult(
        signal=signal,
        score=80.0,
        confidence=confidence,
        reason="テスト用AI判定",
        provider="test",
        available=available,
    )


def test_buy_is_accepted_when_technical_and_ai_agree() -> None:
    result = determine_final_decision(
        "BUY",
        create_ai_result(signal="BUY", confidence=85.0),
    )

    assert result.signal == "BUY"
    assert result.technical_signal == "BUY"
    assert result.ai_signal == "BUY"


def test_sell_is_accepted_when_technical_and_ai_agree() -> None:
    result = determine_final_decision(
        "SELL",
        create_ai_result(signal="SELL", confidence=90.0),
    )

    assert result.signal == "SELL"


def test_disagreement_becomes_hold() -> None:
    result = determine_final_decision(
        "BUY",
        create_ai_result(signal="SELL", confidence=90.0),
    )

    assert result.signal == "HOLD"
    assert "一致しない" in result.reason


def test_low_ai_confidence_becomes_hold() -> None:
    result = determine_final_decision(
        "BUY",
        create_ai_result(signal="BUY", confidence=69.9),
    )

    assert result.signal == "HOLD"
    assert "基準未満" in result.reason


def test_unavailable_ai_becomes_hold() -> None:
    result = determine_final_decision(
        "BUY",
        create_ai_result(
            signal="HOLD",
            confidence=0.0,
            available=False,
        ),
    )

    assert result.signal == "HOLD"
    assert result.ai_available is False


def test_technical_hold_remains_hold() -> None:
    result = determine_final_decision(
        "HOLD",
        create_ai_result(signal="BUY", confidence=90.0),
    )

    assert result.signal == "HOLD"


def test_confidence_threshold_can_be_changed() -> None:
    result = determine_final_decision(
        "BUY",
        create_ai_result(signal="BUY", confidence=60.0),
        minimum_ai_confidence=60.0,
    )

    assert result.signal == "BUY"


def test_invalid_technical_signal_is_treated_as_hold() -> None:
    result = determine_final_decision(
        "UNKNOWN",
        create_ai_result(signal="BUY", confidence=90.0),
    )

    assert result.signal == "HOLD"
    assert result.technical_signal == "HOLD"

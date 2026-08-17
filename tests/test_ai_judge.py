from ai_asset_platform.ai import create_safe_fallback, judge_with_ai


def test_create_safe_fallback_returns_hold():
    result = create_safe_fallback()

    assert result.signal == "HOLD"
    assert result.score == 50.0
    assert result.confidence == 0.0
    assert result.provider == "none"
    assert result.available is False


def test_judge_with_ai_returns_fallback_without_provider():
    result = judge_with_ai({"ticker": "7203.T"})

    assert result.signal == "HOLD"
    assert result.available is False
    assert "AI" in result.reason


def test_judge_with_ai_uses_provider_result():
    class FakeProvider:
        name = "fake-ai"

        def evaluate(self, market_data):
            assert market_data["ticker"] == "7203.T"
            return {
                "signal": "BUY",
                "score": 82,
                "confidence": 75,
                "reason": "上昇傾向が確認できます。",
            }

    result = judge_with_ai(
        {"ticker": "7203.T"},
        provider=FakeProvider(),
    )

    assert result.signal == "BUY"
    assert result.score == 82.0
    assert result.confidence == 75.0
    assert result.provider == "fake-ai"
    assert result.available is True


def test_judge_with_ai_normalizes_invalid_values():
    class InvalidProvider:
        name = "invalid-ai"

        def evaluate(self, market_data):
            return {
                "signal": "UNKNOWN",
                "score": 200,
                "confidence": -10,
                "reason": "",
            }

    result = judge_with_ai({}, provider=InvalidProvider())

    assert result.signal == "HOLD"
    assert result.score == 100.0
    assert result.confidence == 0.0
    assert result.available is True


def test_judge_with_ai_returns_fallback_when_provider_fails():
    class FailingProvider:
        name = "failing-ai"

        def evaluate(self, market_data):
            raise RuntimeError("接続失敗")

    result = judge_with_ai({}, provider=FailingProvider())

    assert result.signal == "HOLD"
    assert result.available is False
    assert "接続失敗" in result.reason


def test_judge_with_ai_returns_fallback_for_invalid_response():
    class InvalidResponseProvider:
        name = "invalid-response"

        def evaluate(self, market_data):
            return "BUY"

    result = judge_with_ai({}, provider=InvalidResponseProvider())

    assert result.signal == "HOLD"
    assert result.available is False
    assert "形式" in result.reason

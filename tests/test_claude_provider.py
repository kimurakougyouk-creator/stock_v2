import pytest

from ai_asset_platform.ai import (
    ClaudeProvider,
    create_provider,
    get_available_providers,
    judge_with_ai,
)


def test_claude_provider_uses_default_model():
    provider = ClaudeProvider()

    assert provider.name == "claude"
    assert provider.model == "claude-default"


def test_claude_provider_rejects_empty_model():
    with pytest.raises(ValueError, match="モデル名"):
        ClaudeProvider(model="   ")


def test_claude_provider_builds_system_prompt():
    prompt = ClaudeProvider.build_system_prompt()

    assert "BUY" in prompt
    assert "SELL" in prompt
    assert "HOLD" in prompt
    assert "confidence" in prompt


def test_claude_provider_builds_user_prompt():
    prompt = ClaudeProvider.build_user_prompt(
        {
            "ticker": "7203.T",
            "technical_signal": "BUY",
            "score": 80,
        }
    )

    assert "7203.T" in prompt
    assert "technical_signal: BUY" in prompt
    assert "score: 80" in prompt


def test_claude_provider_rejects_invalid_market_data():
    with pytest.raises(TypeError, match="辞書形式"):
        ClaudeProvider.build_user_prompt(["7203.T"])


def test_claude_provider_requires_request_function():
    provider = ClaudeProvider()

    with pytest.raises(RuntimeError, match="未設定"):
        provider.evaluate({"ticker": "7203.T"})


def test_claude_provider_calls_request_function():
    captured = {}

    def fake_request(model, system_prompt, payload):
        captured["model"] = model
        captured["system_prompt"] = system_prompt
        captured["payload"] = payload

        return {
            "signal": "BUY",
            "score": 86,
            "confidence": 83,
            "reason": "上昇材料が下落リスクを上回っています。",
        }

    provider = ClaudeProvider(
        model="test-claude-model",
        request_function=fake_request,
    )

    result = provider.evaluate({"ticker": "7203.T"})

    assert result["signal"] == "BUY"
    assert captured["model"] == "test-claude-model"
    assert "AI Judge" in captured["system_prompt"]
    assert captured["payload"]["market_data"]["ticker"] == "7203.T"


def test_claude_provider_rejects_invalid_response():
    def invalid_request(model, system_prompt, payload):
        return "BUY"

    provider = ClaudeProvider(request_function=invalid_request)

    with pytest.raises(TypeError, match="辞書形式"):
        provider.evaluate({"ticker": "7203.T"})


def test_claude_provider_is_registered():
    assert "claude" in get_available_providers()

    provider = create_provider("claude")

    assert isinstance(provider, ClaudeProvider)


def test_all_three_ai_providers_are_registered():
    available = get_available_providers()

    assert "openai" in available
    assert "gemini" in available
    assert "claude" in available


def test_ai_judge_returns_safe_hold_without_claude_connection():
    provider = create_provider("claude")

    result = judge_with_ai(
        {"ticker": "7203.T"},
        provider=provider,
    )

    assert result.signal == "HOLD"
    assert result.available is False
    assert "Claude通信機能が未設定" in result.reason


def test_ai_judge_accepts_claude_provider_result():
    def fake_request(model, system_prompt, payload):
        return {
            "signal": "SELL",
            "score": 15,
            "confidence": 94,
            "reason": "下落リスクが高いと判断されました。",
        }

    provider = create_provider(
        "claude",
        request_function=fake_request,
    )

    result = judge_with_ai(
        {"ticker": "7203.T"},
        provider=provider,
    )

    assert result.signal == "SELL"
    assert result.score == 15.0
    assert result.confidence == 94.0
    assert result.provider == "claude"
    assert result.available is True

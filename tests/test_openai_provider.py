import pytest

from ai_asset_platform.ai import (
    OpenAIProvider,
    create_provider,
    get_available_providers,
    judge_with_ai,
)


def test_openai_provider_uses_default_model():
    provider = OpenAIProvider()

    assert provider.name == "openai"
    assert provider.model == "gpt-4.1-mini"


def test_openai_provider_rejects_empty_model():
    with pytest.raises(ValueError, match="モデル名"):
        OpenAIProvider(model="   ")


def test_openai_provider_builds_system_prompt():
    prompt = OpenAIProvider.build_system_prompt()

    assert "BUY" in prompt
    assert "SELL" in prompt
    assert "HOLD" in prompt
    assert "confidence" in prompt


def test_openai_provider_builds_user_prompt():
    prompt = OpenAIProvider.build_user_prompt(
        {
            "ticker": "7203.T",
            "technical_signal": "BUY",
            "score": 80,
        }
    )

    assert "7203.T" in prompt
    assert "technical_signal: BUY" in prompt
    assert "score: 80" in prompt


def test_openai_provider_rejects_invalid_market_data():
    with pytest.raises(TypeError, match="辞書形式"):
        OpenAIProvider.build_user_prompt(["7203.T"])


def test_openai_provider_requires_request_function():
    provider = OpenAIProvider()

    with pytest.raises(RuntimeError, match="未設定"):
        provider.evaluate({"ticker": "7203.T"})


def test_openai_provider_calls_request_function():
    captured = {}

    def fake_request(model, system_prompt, payload):
        captured["model"] = model
        captured["system_prompt"] = system_prompt
        captured["payload"] = payload

        return {
            "signal": "BUY",
            "score": 85,
            "confidence": 78,
            "reason": "上昇傾向が確認されました。",
        }

    provider = OpenAIProvider(
        model="test-model",
        request_function=fake_request,
    )

    result = provider.evaluate({"ticker": "7203.T"})

    assert result["signal"] == "BUY"
    assert captured["model"] == "test-model"
    assert "AI Judge" in captured["system_prompt"]
    assert captured["payload"]["market_data"]["ticker"] == "7203.T"


def test_openai_provider_rejects_invalid_response():
    def invalid_request(model, system_prompt, payload):
        return "BUY"

    provider = OpenAIProvider(request_function=invalid_request)

    with pytest.raises(TypeError, match="辞書形式"):
        provider.evaluate({"ticker": "7203.T"})


def test_openai_provider_is_registered():
    assert "openai" in get_available_providers()

    provider = create_provider("openai")

    assert isinstance(provider, OpenAIProvider)


def test_ai_judge_returns_safe_hold_without_openai_connection():
    provider = create_provider("openai")

    result = judge_with_ai(
        {"ticker": "7203.T"},
        provider=provider,
    )

    assert result.signal == "HOLD"
    assert result.available is False
    assert "OpenAI通信機能が未設定" in result.reason


def test_ai_judge_accepts_openai_provider_result():
    def fake_request(model, system_prompt, payload):
        return {
            "signal": "SELL",
            "score": 20,
            "confidence": 90,
            "reason": "下落リスクが高まっています。",
        }

    provider = create_provider(
        "openai",
        request_function=fake_request,
    )

    result = judge_with_ai(
        {"ticker": "7203.T"},
        provider=provider,
    )

    assert result.signal == "SELL"
    assert result.score == 20.0
    assert result.confidence == 90.0
    assert result.provider == "openai"
    assert result.available is True

class FakeResponse:
    def __init__(self, output_text):
        self.output_text = output_text


class FakeResponses:
    def __init__(self, output_text):
        self.output_text = output_text
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return FakeResponse(self.output_text)


class FakeOpenAIClient:
    def __init__(self, output_text):
        self.responses = FakeResponses(output_text)


def test_openai_provider_connects_to_openai_client():
    fake_client = FakeOpenAIClient(
        '{"signal":"BUY","score":88,'
        '"confidence":91,"reason":"上昇傾向です。"}'
    )

    provider = OpenAIProvider(
        model="test-model",
        api_key="test-api-key",
        client=fake_client,
    )

    result = provider.evaluate(
        {
            "ticker": "7203.T",
            "technical_signal": "BUY",
        }
    )

    assert result["signal"] == "BUY"
    assert result["score"] == 88

    call = fake_client.responses.calls[0]

    assert call["model"] == "test-model"
    assert "7203.T" in call["input"]
    assert "JSON形式" in call["instructions"]


def test_openai_provider_prefers_request_function():
    captured = {}

    def fake_request(model, system_prompt, payload):
        captured["called"] = True
        return {
            "signal": "HOLD",
            "score": 50,
            "confidence": 70,
            "reason": "様子見です。",
        }

    provider = OpenAIProvider(
        api_key="test-api-key",
        request_function=fake_request,
    )

    result = provider.evaluate({"ticker": "7203.T"})

    assert result["signal"] == "HOLD"
    assert captured["called"] is True
    assert provider.openai_client is None


def test_ai_judge_uses_connected_openai_client():
    fake_client = FakeOpenAIClient(
        '{"signal":"SELL","score":25,'
        '"confidence":89,"reason":"下落リスクです。"}'
    )

    provider = create_provider(
        "openai",
        model="test-model",
        api_key="test-api-key",
        client=fake_client,
    )

    result = judge_with_ai(
        {"ticker": "7203.T"},
        provider=provider,
    )

    assert result.signal == "SELL"
    assert result.score == 25.0
    assert result.confidence == 89.0
    assert result.provider == "openai"
    assert result.available is True


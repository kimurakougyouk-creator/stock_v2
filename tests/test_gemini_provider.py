import json

import pytest

from ai_asset_platform.ai import (
    GeminiProvider,
    create_provider,
    get_available_providers,
    judge_with_ai,
)


class _FakeHTTPResponse:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> "_FakeHTTPResponse":
        return self

    def __exit__(self, *args: object) -> bool:
        return False


def _fake_opener_returning(result: dict):
    body = json.dumps(
        {"candidates": [{"content": {"parts": [{"text": json.dumps(result)}]}}]}
    ).encode("utf-8")

    def _opener(request, timeout):  # noqa: ANN001
        return _FakeHTTPResponse(body)

    return _opener


def test_gemini_provider_uses_default_model():
    provider = GeminiProvider()

    assert provider.name == "gemini"
    assert provider.model == "gemini-default"


def test_gemini_provider_rejects_empty_model():
    with pytest.raises(ValueError, match="モデル名"):
        GeminiProvider(model="   ")


def test_gemini_provider_builds_system_prompt():
    prompt = GeminiProvider.build_system_prompt()

    assert "BUY" in prompt
    assert "SELL" in prompt
    assert "HOLD" in prompt
    assert "confidence" in prompt


def test_gemini_provider_builds_user_prompt():
    prompt = GeminiProvider.build_user_prompt(
        {
            "ticker": "7203.T",
            "technical_signal": "BUY",
            "score": 80,
        }
    )

    assert "7203.T" in prompt
    assert "technical_signal: BUY" in prompt
    assert "score: 80" in prompt


def test_gemini_provider_rejects_invalid_market_data():
    with pytest.raises(TypeError, match="辞書形式"):
        GeminiProvider.build_user_prompt(["7203.T"])


def test_gemini_provider_requires_request_function():
    provider = GeminiProvider()

    with pytest.raises(RuntimeError, match="未設定"):
        provider.evaluate({"ticker": "7203.T"})


def test_gemini_provider_calls_request_function():
    captured = {}

    def fake_request(model, system_prompt, payload):
        captured["model"] = model
        captured["system_prompt"] = system_prompt
        captured["payload"] = payload

        return {
            "signal": "BUY",
            "score": 88,
            "confidence": 81,
            "reason": "複数の上昇材料が確認されました。",
        }

    provider = GeminiProvider(
        model="test-gemini-model",
        request_function=fake_request,
    )

    result = provider.evaluate({"ticker": "7203.T"})

    assert result["signal"] == "BUY"
    assert captured["model"] == "test-gemini-model"
    assert "AI Judge" in captured["system_prompt"]
    assert captured["payload"]["market_data"]["ticker"] == "7203.T"


def test_gemini_provider_rejects_invalid_response():
    def invalid_request(model, system_prompt, payload):
        return "BUY"

    provider = GeminiProvider(request_function=invalid_request)

    with pytest.raises(TypeError, match="辞書形式"):
        provider.evaluate({"ticker": "7203.T"})


def test_gemini_provider_accepts_api_key_without_crashing():
    # Regression: create_provider() always calls providers with
    # model=..., api_key=... (see signal_runner._create_configured_ai_provider).
    # Before this fix, GeminiProvider.__init__ had no api_key parameter, so
    # selecting AI_PROVIDER=gemini with a configured GEMINI_API_KEY raised an
    # unrelated TypeError. A fake opener is injected so this never attempts a
    # real network call (mock test, not a real-API test).
    provider = create_provider(
        "gemini",
        model="gemini-1.5-flash",
        api_key="dummy-key",
        opener=lambda *a, **k: (_ for _ in ()).throw(
            AssertionError("must not be called in this test")
        ),
    )

    assert provider.api_key == "dummy-key"
    assert provider.gemini_client is not None


def test_gemini_provider_rejects_placeholder_model_with_api_key():
    # Regression for Codex P1 finding on PR #354: AISettings.gemini_model's
    # own default ("gemini-default") is not a real Gemini model id. Without
    # this check, setting only GEMINI_API_KEY (and forgetting GEMINI_MODEL)
    # would silently send requests to a nonexistent model and fall back to
    # HOLD via judge_with_ai()'s broad exception handling, hiding the
    # misconfiguration instead of surfacing it clearly at construction time.
    with pytest.raises(ValueError, match="GEMINI_MODEL"):
        create_provider("gemini", model="gemini-default", api_key="dummy-key")


def test_gemini_provider_placeholder_model_is_fine_without_api_key():
    # The placeholder is only rejected once it would actually be used to
    # build a real client; with no api_key, nothing is sent anywhere.
    provider = create_provider("gemini", model="gemini-default")

    assert provider.model == "gemini-default"
    assert provider.gemini_client is None


def test_gemini_provider_without_api_key_stays_on_safe_hold_message():
    provider = create_provider("gemini", model="gemini-default")

    result = judge_with_ai({"ticker": "7203.T"}, provider=provider)

    assert result.signal == "HOLD"
    assert result.available is False
    assert "Gemini通信機能が未設定" in result.reason


def test_gemini_provider_with_api_key_calls_real_client_mocked():
    # Mock test (no real network): confirms api_key actually wires up a
    # functioning GeminiClient end to end through judge_with_ai().
    opener = _fake_opener_returning(
        {"signal": "SELL", "score": 20, "confidence": 88, "reason": "下落材料"}
    )
    provider = create_provider(
        "gemini",
        model="gemini-1.5-flash",
        api_key="dummy-key",
        opener=opener,
    )

    result = judge_with_ai({"ticker": "7203.T"}, provider=provider)

    assert result.signal == "SELL"
    assert result.score == 20.0
    assert result.confidence == 88.0
    assert result.available is True
    assert result.provider == "gemini"


def test_gemini_provider_explicit_request_function_overrides_real_client():
    # An explicitly supplied request_function (e.g. for other tests) takes
    # priority over building a real GeminiClient, even if api_key is set.
    def fake_request(model, system_prompt, payload):
        return {"signal": "HOLD", "score": 50, "confidence": 0, "reason": "x"}

    provider = GeminiProvider(
        api_key="dummy-key",
        request_function=fake_request,
    )

    assert provider.gemini_client is None


def test_gemini_provider_threads_generation_limits_to_client():
    # Root-cause investigation (2026-10-26): generationConfig previously
    # had no maxOutputTokens/thinkingConfig, letting a thinking-capable
    # model spend unbounded time before responding. Confirms the
    # provider's constructor params actually reach GeminiClient rather
    # than being silently dropped.
    captured = {}

    def _opener(request, timeout):  # noqa: ANN001
        captured["body"] = json.loads(request.data.decode("utf-8"))
        body = json.dumps(
            {
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {
                                    "text": json.dumps(
                                        {
                                            "signal": "HOLD",
                                            "score": 50,
                                            "confidence": 0,
                                            "reason": "x",
                                        }
                                    )
                                }
                            ]
                        }
                    }
                ]
            }
        ).encode("utf-8")
        return _FakeHTTPResponse(body)

    provider = create_provider(
        "gemini",
        model="gemini-3.8-flash",
        api_key="dummy-key",
        opener=_opener,
        max_output_tokens=256,
        thinking_level="medium",
    )

    judge_with_ai({"ticker": "7203.T"}, provider=provider)

    generation_config = captured["body"]["generationConfig"]
    assert generation_config["maxOutputTokens"] == 256
    assert generation_config["thinkingConfig"] == {"thinkingLevel": "medium"}


def test_gemini_provider_is_registered():
    assert "gemini" in get_available_providers()

    provider = create_provider("gemini")

    assert isinstance(provider, GeminiProvider)


def test_openai_and_gemini_are_both_registered():
    available = get_available_providers()

    assert "openai" in available
    assert "gemini" in available


def test_ai_judge_falls_back_to_hold_on_timeout():
    # Root-cause investigation (2026-10-26): a real generateContent call
    # hung well past 60s before the maxOutputTokens/thinkingConfig bounds
    # were added in PR #366. A bare timeout from urlopen() (TimeoutError,
    # not wrapped in urllib.error.URLError) is not caught by GeminiClient's
    # own except clauses and propagates unchanged through
    # GeminiProvider.evaluate(); this confirms judge_with_ai()'s broad
    # except Exception still fails closed to a safe HOLD in that case,
    # end to end, with no real network call.
    def _timing_out_opener(request, timeout):  # noqa: ANN001
        raise TimeoutError("simulated urlopen timeout")

    provider = create_provider(
        "gemini",
        model="gemini-3.8-flash",
        api_key="dummy-key",
        opener=_timing_out_opener,
    )

    result = judge_with_ai({"ticker": "7203.T"}, provider=provider)

    assert result.signal == "HOLD"
    assert result.available is False


def test_ai_judge_returns_safe_hold_without_gemini_connection():
    provider = create_provider("gemini")

    result = judge_with_ai(
        {"ticker": "7203.T"},
        provider=provider,
    )

    assert result.signal == "HOLD"
    assert result.available is False
    assert "Gemini通信機能が未設定" in result.reason


def test_ai_judge_accepts_gemini_provider_result():
    def fake_request(model, system_prompt, payload):
        return {
            "signal": "SELL",
            "score": 18,
            "confidence": 92,
            "reason": "下落材料が優勢です。",
        }

    provider = create_provider(
        "gemini",
        request_function=fake_request,
    )

    result = judge_with_ai(
        {"ticker": "7203.T"},
        provider=provider,
    )

    assert result.signal == "SELL"
    assert result.score == 18.0
    assert result.confidence == 92.0
    assert result.provider == "gemini"
    assert result.available is True

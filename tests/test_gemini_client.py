from __future__ import annotations

import json
import urllib.error

import pytest

from ai_asset_platform.ai.gemini_client import GeminiClient


class _FakeHTTPResponse:
    """urllib.request.urlopen()の戻り値(コンテキストマネージャ)を模倣する。"""

    def __init__(self, body: bytes) -> None:
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> "_FakeHTTPResponse":
        return self

    def __exit__(self, *args: object) -> bool:
        return False


def _gemini_envelope(inner: object) -> bytes:
    inner_text = inner if isinstance(inner, str) else json.dumps(inner)
    return json.dumps(
        {
            "candidates": [
                {"content": {"parts": [{"text": inner_text}]}},
            ],
        }
    ).encode("utf-8")


def _opener_returning(body: bytes):
    captured: dict = {}

    def _opener(request, timeout):  # noqa: ANN001
        captured["request"] = request
        captured["timeout"] = timeout
        return _FakeHTTPResponse(body)

    return _opener, captured


def test_rejects_empty_api_key():
    with pytest.raises(ValueError, match="APIキー"):
        GeminiClient(api_key="")


def test_rejects_non_positive_timeout():
    with pytest.raises(ValueError, match="timeout"):
        GeminiClient(api_key="dummy", timeout=0)


def test_rejects_empty_model():
    client = GeminiClient(api_key="dummy", opener=lambda *a, **k: None)

    with pytest.raises(ValueError, match="モデル名"):
        client.request("", "system", {"prompt": "hello"})


def test_rejects_empty_prompt():
    client = GeminiClient(api_key="dummy", opener=lambda *a, **k: None)

    with pytest.raises(ValueError, match="プロンプト"):
        client.request("gemini-1.5-flash", "system", {"prompt": ""})


def test_rejects_non_mapping_payload():
    client = GeminiClient(api_key="dummy", opener=lambda *a, **k: None)

    with pytest.raises(TypeError, match="辞書形式"):
        client.request("gemini-1.5-flash", "system", "not-a-mapping")


def test_successful_request_parses_inner_json_result():
    body = _gemini_envelope(
        {"signal": "BUY", "score": 90, "confidence": 85, "reason": "強い上昇トレンド"}
    )
    opener, captured = _opener_returning(body)
    client = GeminiClient(api_key="dummy-key", opener=opener)

    result = client.request(
        "gemini-1.5-flash", "system-prompt", {"prompt": "evaluate this"}
    )

    assert result == {
        "signal": "BUY",
        "score": 90,
        "confidence": 85,
        "reason": "強い上昇トレンド",
    }


def test_api_key_is_sent_as_header_not_in_url():
    body = _gemini_envelope({"signal": "HOLD", "score": 50, "confidence": 0, "reason": "x"})
    opener, captured = _opener_returning(body)
    client = GeminiClient(api_key="dummy-secret-key-value", opener=opener)

    client.request("gemini-1.5-flash", "system", {"prompt": "x"})

    sent_request = captured["request"]
    assert sent_request.headers.get("X-goog-api-key") == "dummy-secret-key-value"
    assert "dummy-secret-key-value" not in sent_request.full_url


def test_http_error_is_raised_as_runtime_error_without_leaking_key():
    def _opener(request, timeout):  # noqa: ANN001
        raise urllib.error.HTTPError(
            request.full_url, 403, "Forbidden", {}, None
        )

    client = GeminiClient(api_key="dummy-secret-key-value", opener=_opener)

    with pytest.raises(RuntimeError) as excinfo:
        client.request("gemini-1.5-flash", "system", {"prompt": "x"})

    assert "dummy-secret-key-value" not in str(excinfo.value)
    assert "403" in str(excinfo.value)


def test_generation_config_bounds_output_tokens_and_thinking_by_default():
    # Root-cause investigation (2026-10-26): a real API key authenticates
    # instantly against the lightweight models.get endpoint, but a real
    # generateContent call hangs well past 60s even for a trivial prompt.
    # generationConfig previously had no maxOutputTokens/thinkingConfig,
    # so a thinking-capable model (e.g. gemini-3.8-flash) could spend an
    # unbounded number of internal "thinking" tokens before ever
    # producing output. The AI Judge only needs a short structured JSON
    # classification, not deep reasoning, so both are now bounded by
    # safe defaults unless explicitly overridden.
    body = _gemini_envelope({"signal": "HOLD", "score": 50, "confidence": 0, "reason": "x"})
    opener, captured = _opener_returning(body)
    client = GeminiClient(api_key="dummy", opener=opener)

    client.request("gemini-3.8-flash", "system", {"prompt": "x"})

    sent_body = json.loads(captured["request"].data.decode("utf-8"))
    generation_config = sent_body["generationConfig"]
    # Codex review (PR #366, comment 4373702365): maxOutputTokens covers
    # thinking tokens too; 512 left no headroom for reasoning before the
    # final JSON, risking truncation. 2048 leaves room for "low"-level
    # thinking plus the short response.
    assert generation_config["maxOutputTokens"] == 2048
    assert generation_config["thinkingConfig"] == {"thinkingLevel": "low"}
    assert generation_config["responseMimeType"] == "application/json"


def test_thinking_config_uses_budget_field_for_gemini_2_5_models():
    # Codex review (PR #366, comment 4373702357): Gemini 2.5 models use
    # thinkingConfig.thinkingBudget (an integer), not thinkingLevel, and
    # reject the latter. The client must gate the field by model.
    body = _gemini_envelope({"signal": "HOLD", "score": 50, "confidence": 0, "reason": "x"})
    opener, captured = _opener_returning(body)
    client = GeminiClient(api_key="dummy", opener=opener)

    client.request("gemini-2.5-flash", "system", {"prompt": "x"})

    generation_config = json.loads(captured["request"].data.decode("utf-8"))[
        "generationConfig"
    ]
    assert generation_config["thinkingConfig"] == {"thinkingBudget": 512}
    assert "thinkingLevel" not in generation_config["thinkingConfig"]


def test_thinking_config_is_omitted_for_non_thinking_models():
    # Codex review (PR #366, comment 4373702357): older/non-thinking
    # models (e.g. 1.x, 2.0) support neither field; sending either
    # unconditionally would turn a previously valid request into an API
    # error. The default thinking_level="low" must be silently dropped
    # for a model that doesn't recognize it, without the caller having
    # to know to pass thinking_level=None themselves.
    body = _gemini_envelope({"signal": "HOLD", "score": 50, "confidence": 0, "reason": "x"})
    opener, captured = _opener_returning(body)
    client = GeminiClient(api_key="dummy", opener=opener)

    client.request("gemini-1.5-flash", "system", {"prompt": "x"})

    generation_config = json.loads(captured["request"].data.decode("utf-8"))[
        "generationConfig"
    ]
    assert "thinkingConfig" not in generation_config
    # maxOutputTokens is unrelated to thinking-field gating and still applies.
    assert generation_config["maxOutputTokens"] == 2048


def test_generation_config_limits_are_configurable():
    body = _gemini_envelope({"signal": "HOLD", "score": 50, "confidence": 0, "reason": "x"})
    opener, captured = _opener_returning(body)
    client = GeminiClient(
        api_key="dummy",
        opener=opener,
        max_output_tokens=128,
        thinking_level="high",
    )

    client.request("gemini-3.8-flash", "system", {"prompt": "x"})

    generation_config = json.loads(captured["request"].data.decode("utf-8"))[
        "generationConfig"
    ]
    assert generation_config["maxOutputTokens"] == 128
    assert generation_config["thinkingConfig"] == {"thinkingLevel": "high"}


def test_generation_config_limits_can_be_disabled_explicitly():
    # Some older/non-thinking models could reject an unrecognized
    # thinkingConfig field; callers must be able to opt out entirely
    # rather than being forced into these new defaults.
    body = _gemini_envelope({"signal": "HOLD", "score": 50, "confidence": 0, "reason": "x"})
    opener, captured = _opener_returning(body)
    client = GeminiClient(
        api_key="dummy",
        opener=opener,
        max_output_tokens=None,
        thinking_level=None,
    )

    client.request("gemini-1.5-flash", "system", {"prompt": "x"})

    generation_config = json.loads(captured["request"].data.decode("utf-8"))[
        "generationConfig"
    ]
    assert "maxOutputTokens" not in generation_config
    assert "thinkingConfig" not in generation_config


def test_rejects_non_positive_max_output_tokens():
    with pytest.raises(ValueError, match="max_output_tokens"):
        GeminiClient(api_key="dummy", max_output_tokens=0)


def test_url_error_is_raised_as_runtime_error():
    def _opener(request, timeout):  # noqa: ANN001
        raise urllib.error.URLError("name resolution failed")

    client = GeminiClient(api_key="dummy", opener=_opener)

    with pytest.raises(RuntimeError, match="Gemini API通信に失敗"):
        client.request("gemini-1.5-flash", "system", {"prompt": "x"})


def test_malformed_top_level_json_fails_closed():
    opener, _ = _opener_returning(b"not json at all")
    client = GeminiClient(api_key="dummy", opener=opener)

    with pytest.raises(ValueError, match="JSON"):
        client.request("gemini-1.5-flash", "system", {"prompt": "x"})


def test_missing_candidates_fails_closed():
    body = json.dumps({"no_candidates_here": True}).encode("utf-8")
    opener, _ = _opener_returning(body)
    client = GeminiClient(api_key="dummy", opener=opener)

    with pytest.raises(RuntimeError, match="応答形式"):
        client.request("gemini-1.5-flash", "system", {"prompt": "x"})


def test_empty_inner_text_fails_closed():
    body = _gemini_envelope("")
    opener, _ = _opener_returning(body)
    client = GeminiClient(api_key="dummy", opener=opener)

    with pytest.raises(RuntimeError, match="空の応答"):
        client.request("gemini-1.5-flash", "system", {"prompt": "x"})


def test_non_json_inner_text_fails_closed():
    body = _gemini_envelope("this is not JSON")
    opener, _ = _opener_returning(body)
    client = GeminiClient(api_key="dummy", opener=opener)

    with pytest.raises(ValueError, match="JSON"):
        client.request("gemini-1.5-flash", "system", {"prompt": "x"})


def test_non_mapping_inner_result_fails_closed():
    body = _gemini_envelope(["BUY"])
    opener, _ = _opener_returning(body)
    client = GeminiClient(api_key="dummy", opener=opener)

    with pytest.raises(TypeError, match="辞書形式"):
        client.request("gemini-1.5-flash", "system", {"prompt": "x"})

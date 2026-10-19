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
    client = GeminiClient(api_key="SECRET-KEY-VALUE", opener=opener)

    client.request("gemini-1.5-flash", "system", {"prompt": "x"})

    sent_request = captured["request"]
    assert sent_request.headers.get("X-goog-api-key") == "SECRET-KEY-VALUE"
    assert "SECRET-KEY-VALUE" not in sent_request.full_url


def test_http_error_is_raised_as_runtime_error_without_leaking_key():
    def _opener(request, timeout):  # noqa: ANN001
        raise urllib.error.HTTPError(
            request.full_url, 403, "Forbidden", {}, None
        )

    client = GeminiClient(api_key="SECRET-KEY-VALUE", opener=_opener)

    with pytest.raises(RuntimeError) as excinfo:
        client.request("gemini-1.5-flash", "system", {"prompt": "x"})

    assert "SECRET-KEY-VALUE" not in str(excinfo.value)
    assert "403" in str(excinfo.value)


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

from signal_runner import _create_configured_ai_provider

from ai_asset_platform.ai.providers import (
    ClaudeProvider,
    GeminiProvider,
    OpenAIProvider,
)


def _clear_ai_env(monkeypatch):
    for key in (
        "AI_ENABLED",
        "AI_PROVIDER",
        "OPENAI_API_KEY",
        "GEMINI_API_KEY",
        "ANTHROPIC_API_KEY",
    ):
        monkeypatch.delenv(key, raising=False)


def test_no_provider_configured_returns_none(monkeypatch, tmp_path):
    _clear_ai_env(monkeypatch)
    monkeypatch.chdir(tmp_path)

    assert _create_configured_ai_provider() is None


def test_openai_provider_is_constructed_when_configured(monkeypatch, tmp_path):
    _clear_ai_env(monkeypatch)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("AI_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "dummy-key")

    provider = _create_configured_ai_provider()

    assert isinstance(provider, OpenAIProvider)


def test_gemini_provider_is_constructed_when_configured(monkeypatch, tmp_path):
    # Regression: before fixing GeminiProvider.__init__ to accept api_key,
    # this raised an unrelated TypeError one level up and was silently
    # swallowed into "AI設定の読み込みに失敗したため、AI評価をスキップします",
    # which looked identical to "nothing configured" and hid the real bug.
    _clear_ai_env(monkeypatch)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("AI_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "dummy-key")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-1.5-flash")

    provider = _create_configured_ai_provider()

    assert isinstance(provider, GeminiProvider)


def test_gemini_provider_with_placeholder_model_fails_closed_to_none(monkeypatch, tmp_path):
    # Regression for Codex P1 finding on PR #354: if the operator sets
    # GEMINI_API_KEY but forgets GEMINI_MODEL, AISettings.gemini_model falls
    # back to its own placeholder default ("gemini-default"), which is not a
    # real model id. _create_configured_ai_provider() must not silently
    # construct a client that would only fail later inside a real API call;
    # it must fail closed to None here, exactly like "nothing configured".
    _clear_ai_env(monkeypatch)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("AI_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "dummy-key")

    assert _create_configured_ai_provider() is None


def test_claude_provider_is_constructed_when_configured(monkeypatch, tmp_path):
    _clear_ai_env(monkeypatch)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("AI_PROVIDER", "claude")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "dummy-key")

    provider = _create_configured_ai_provider()

    assert isinstance(provider, ClaudeProvider)

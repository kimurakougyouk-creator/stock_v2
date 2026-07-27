import pytest

from ai_asset_platform.ai.settings import (
    AISettings,
    SUPPORTED_AI_PROVIDERS,
    load_ai_settings,
)


def test_supported_ai_providers():
    assert SUPPORTED_AI_PROVIDERS == (
        "openai",
        "gemini",
        "claude",
    )


def test_ai_settings_default_values():
    settings = AISettings()

    assert settings.enabled is True
    assert settings.provider == "openai"
    assert settings.openai_model == "gpt-4.1-mini"
    assert settings.gemini_model == "gemini-default"
    assert settings.claude_model == "claude-default"
    assert settings.is_available is False


def test_ai_settings_normalizes_provider():
    settings = AISettings(provider="  GEMINI  ")

    assert settings.provider == "gemini"


def test_ai_settings_rejects_unsupported_provider():
    with pytest.raises(ValueError, match="未対応"):
        AISettings(provider="unknown")


def test_ai_settings_rejects_empty_selected_model():
    with pytest.raises(ValueError, match="モデル名"):
        AISettings(
            provider="gemini",
            gemini_model="   ",
        )


def test_ai_settings_returns_selected_api_key():
    settings = AISettings(
        provider="gemini",
        gemini_api_key="gemini-secret",
    )

    assert settings.get_api_key() == "gemini-secret"
    assert settings.has_api_key() is True
    assert settings.is_available is True


def test_ai_settings_returns_other_provider_values():
    settings = AISettings(
        openai_api_key="openai-secret",
        claude_api_key="claude-secret",
        claude_model="claude-test-model",
    )

    assert settings.get_api_key("openai") == "openai-secret"
    assert settings.get_api_key("claude") == "claude-secret"
    assert settings.get_model("claude") == "claude-test-model"


def test_disabled_ai_is_not_available():
    settings = AISettings(
        enabled=False,
        openai_api_key="openai-secret",
    )

    assert settings.has_api_key() is True
    assert settings.is_available is False


def test_safe_dict_does_not_expose_api_key():
    settings = AISettings(
        openai_api_key="top-secret-api-key",
    )

    safe_settings = settings.to_safe_dict()

    assert safe_settings == {
        "enabled": True,
        "provider": "openai",
        "model": "gpt-4.1-mini",
        "api_key_configured": True,
    }
    assert "top-secret-api-key" not in str(safe_settings)


def test_load_ai_settings_from_env_file(tmp_path, monkeypatch):
    for key in (
        "AI_ENABLED",
        "AI_PROVIDER",
        "OPENAI_API_KEY",
        "GEMINI_API_KEY",
        "ANTHROPIC_API_KEY",
        "OPENAI_MODEL",
        "GEMINI_MODEL",
        "CLAUDE_MODEL",
    ):
        monkeypatch.delenv(key, raising=False)

    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "AI_ENABLED=true",
                "AI_PROVIDER=gemini",
                "OPENAI_API_KEY='openai-from-file'",
                "GEMINI_API_KEY='gemini-from-file'",
                "ANTHROPIC_API_KEY='claude-from-file'",
                "OPENAI_MODEL=gpt-test",
                "GEMINI_MODEL=gemini-test",
                "CLAUDE_MODEL=claude-test",
            ]
        ),
        encoding="utf-8",
    )

    settings = load_ai_settings(env_file)

    assert settings.enabled is True
    assert settings.provider == "gemini"
    assert settings.openai_api_key == "openai-from-file"
    assert settings.gemini_api_key == "gemini-from-file"
    assert settings.claude_api_key == "claude-from-file"
    assert settings.openai_model == "gpt-test"
    assert settings.gemini_model == "gemini-test"
    assert settings.claude_model == "claude-test"


def test_environment_variable_overrides_env_file(
    tmp_path,
    monkeypatch,
):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "AI_PROVIDER=gemini\n"
        "GEMINI_API_KEY=file-secret\n",
        encoding="utf-8",
    )

    monkeypatch.setenv("AI_PROVIDER", "claude")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "environment-secret")

    settings = load_ai_settings(env_file)

    assert settings.provider == "claude"
    assert settings.claude_api_key == "environment-secret"


@pytest.mark.parametrize(
    "disabled_value",
    ["0", "false", "False", "no", "off", "disabled"],
)
def test_load_ai_settings_understands_disabled_values(
    tmp_path,
    monkeypatch,
    disabled_value,
):
    monkeypatch.delenv("AI_ENABLED", raising=False)

    env_file = tmp_path / ".env"
    env_file.write_text(
        f"AI_ENABLED={disabled_value}\n",
        encoding="utf-8",
    )

    settings = load_ai_settings(env_file)

    assert settings.enabled is False

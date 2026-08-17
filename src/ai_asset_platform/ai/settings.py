from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


SUPPORTED_AI_PROVIDERS = ("openai", "gemini", "claude")


def _normalize_value(value: object) -> str:
    """Noneや空白を安全な文字列へ変換する。"""

    return str(value or "").strip()


def _resolve_env_path(env_file: str | Path | None = None) -> Path | None:
    """
    読み込む.envファイルを探す。

    優先順位:
    1. 明示的に指定されたファイル
    2. 現在の作業ディレクトリの.env
    3. プロジェクトルートの.env
    """

    candidates: list[Path] = []

    if env_file is not None:
        candidates.append(Path(env_file))

    candidates.append(Path.cwd() / ".env")

    project_root = Path(__file__).resolve().parents[3]
    candidates.append(project_root / ".env")

    checked: set[Path] = set()

    for candidate in candidates:
        resolved_candidate = candidate.expanduser().resolve()

        if resolved_candidate in checked:
            continue

        checked.add(resolved_candidate)

        if resolved_candidate.is_file():
            return resolved_candidate

    return None


def _read_env_file(env_path: Path | None) -> dict[str, str]:
    """簡易的に.envファイルを読み込む。"""

    if env_path is None:
        return {}

    values: dict[str, str] = {}

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()

        if not line or line.startswith("#"):
            continue

        if line.startswith("export "):
            line = line[len("export "):].strip()

        if "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()

        if not key:
            continue

        if (
            len(value) >= 2
            and value[0] == value[-1]
            and value[0] in {"'", '"'}
        ):
            value = value[1:-1]

        values[key] = value

    return values


def _get_setting(
    key: str,
    *,
    env_values: dict[str, str],
    default: str = "",
) -> str:
    """
    設定値を取得する。

    OS環境変数を.envファイルより優先する。
    """

    environment_value = os.getenv(key)

    if environment_value is not None:
        return _normalize_value(environment_value)

    return _normalize_value(env_values.get(key, default))


@dataclass(frozen=True)
class AISettings:
    """AI接続に使用する設定を一元管理する。"""

    enabled: bool = True
    provider: str = "openai"

    openai_api_key: str = ""
    gemini_api_key: str = ""
    claude_api_key: str = ""

    openai_model: str = "gpt-4.1-mini"
    gemini_model: str = "gemini-default"
    claude_model: str = "claude-default"

    def __post_init__(self) -> None:
        normalized_provider = _normalize_value(self.provider).lower()

        if normalized_provider not in SUPPORTED_AI_PROVIDERS:
            available = ", ".join(SUPPORTED_AI_PROVIDERS)
            raise ValueError(
                f"未対応のAIプロバイダーです: "
                f"{normalized_provider or '未指定'}。"
                f"利用可能: {available}"
            )

        object.__setattr__(self, "provider", normalized_provider)

        for field_name in (
            "openai_api_key",
            "gemini_api_key",
            "claude_api_key",
            "openai_model",
            "gemini_model",
            "claude_model",
        ):
            object.__setattr__(
                self,
                field_name,
                _normalize_value(getattr(self, field_name)),
            )

        if not self.get_model():
            raise ValueError(
                f"{self.provider}のモデル名を指定してください。"
            )

    def get_api_key(self, provider: str | None = None) -> str:
        """指定したAIプロバイダーのAPIキーを返す。"""

        normalized_provider = _normalize_value(
            provider or self.provider
        ).lower()

        if normalized_provider not in SUPPORTED_AI_PROVIDERS:
            raise ValueError(
                f"未対応のAIプロバイダーです: "
                f"{normalized_provider or '未指定'}"
            )

        return {
            "openai": self.openai_api_key,
            "gemini": self.gemini_api_key,
            "claude": self.claude_api_key,
        }[normalized_provider]

    def get_model(self, provider: str | None = None) -> str:
        """指定したAIプロバイダーのモデル名を返す。"""

        normalized_provider = _normalize_value(
            provider or self.provider
        ).lower()

        if normalized_provider not in SUPPORTED_AI_PROVIDERS:
            raise ValueError(
                f"未対応のAIプロバイダーです: "
                f"{normalized_provider or '未指定'}"
            )

        return {
            "openai": self.openai_model,
            "gemini": self.gemini_model,
            "claude": self.claude_model,
        }[normalized_provider]

    def has_api_key(self, provider: str | None = None) -> bool:
        """APIキーが設定されているかを返す。"""

        return bool(self.get_api_key(provider))

    @property
    def is_available(self) -> bool:
        """AIが有効で、選択中のAPIキーが存在するかを返す。"""

        return self.enabled and self.has_api_key()

    def to_safe_dict(self) -> dict[str, object]:
        """APIキーを含まない安全な設定情報を返す。"""

        return {
            "enabled": self.enabled,
            "provider": self.provider,
            "model": self.get_model(),
            "api_key_configured": self.has_api_key(),
        }


def load_ai_settings(
    env_file: str | Path | None = None,
) -> AISettings:
    """環境変数または.envファイルからAI設定を読み込む。"""

    env_path = _resolve_env_path(env_file)
    env_values = _read_env_file(env_path)

    enabled_text = _get_setting(
        "AI_ENABLED",
        env_values=env_values,
        default="true",
    ).lower()

    enabled = enabled_text not in {
        "0",
        "false",
        "no",
        "off",
        "disabled",
    }

    return AISettings(
        enabled=enabled,
        provider=_get_setting(
            "AI_PROVIDER",
            env_values=env_values,
            default="openai",
        ),
        openai_api_key=_get_setting(
            "OPENAI_API_KEY",
            env_values=env_values,
        ),
        gemini_api_key=_get_setting(
            "GEMINI_API_KEY",
            env_values=env_values,
        ),
        claude_api_key=_get_setting(
            "ANTHROPIC_API_KEY",
            env_values=env_values,
        ),
        openai_model=_get_setting(
            "OPENAI_MODEL",
            env_values=env_values,
            default="gpt-4.1-mini",
        ),
        gemini_model=_get_setting(
            "GEMINI_MODEL",
            env_values=env_values,
            default="gemini-default",
        ),
        claude_model=_get_setting(
            "CLAUDE_MODEL",
            env_values=env_values,
            default="claude-default",
        ),
    )

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ..ai_judge import AIProvider


ProviderFactory = Callable[..., AIProvider]


class ProviderRegistry:
    """AIプロバイダーを名前で登録・生成する管理クラス。"""

    def __init__(self) -> None:
        self._factories: dict[str, ProviderFactory] = {}

    @staticmethod
    def _normalize_name(name: str) -> str:
        normalized = str(name or "").strip().lower()

        if not normalized:
            raise ValueError("プロバイダー名を指定してください。")

        return normalized

    def register(
        self,
        name: str,
        factory: ProviderFactory,
        *,
        replace: bool = False,
    ) -> None:
        normalized_name = self._normalize_name(name)

        if not callable(factory):
            raise TypeError("factoryには呼び出し可能な値を指定してください。")

        if normalized_name in self._factories and not replace:
            raise ValueError(
                f"AIプロバイダー「{normalized_name}」は登録済みです。"
            )

        self._factories[normalized_name] = factory

    def unregister(self, name: str) -> bool:
        normalized_name = self._normalize_name(name)
        return self._factories.pop(normalized_name, None) is not None

    def is_registered(self, name: str) -> bool:
        normalized_name = self._normalize_name(name)
        return normalized_name in self._factories

    def available_providers(self) -> tuple[str, ...]:
        return tuple(sorted(self._factories))

    def create(self, name: str, **kwargs: Any) -> AIProvider:
        normalized_name = self._normalize_name(name)

        try:
            factory = self._factories[normalized_name]
        except KeyError as exc:
            available = ", ".join(self.available_providers()) or "なし"
            raise ValueError(
                f"AIプロバイダー「{normalized_name}」は未登録です。"
                f"利用可能: {available}"
            ) from exc

        provider = factory(**kwargs)

        if not hasattr(provider, "name"):
            raise TypeError(
                "AIプロバイダーにはname属性が必要です。"
            )

        if not callable(getattr(provider, "evaluate", None)):
            raise TypeError(
                "AIプロバイダーにはevaluateメソッドが必要です。"
            )

        return provider


default_registry = ProviderRegistry()


def register_provider(
    name: str,
    factory: ProviderFactory,
    *,
    replace: bool = False,
) -> None:
    """標準レジストリへAIプロバイダーを登録する。"""

    default_registry.register(name, factory, replace=replace)


def create_provider(name: str, **kwargs: Any) -> AIProvider:
    """標準レジストリからAIプロバイダーを生成する。"""

    return default_registry.create(name, **kwargs)


def get_available_providers() -> tuple[str, ...]:
    """登録済みのAIプロバイダー名を返す。"""

    return default_registry.available_providers()

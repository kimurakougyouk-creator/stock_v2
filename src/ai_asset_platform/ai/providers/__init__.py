from .gemini_provider import GeminiProvider, GeminiRequestFunction
from .openai_provider import OpenAIProvider, OpenAIRequestFunction
from .registry import (
    ProviderRegistry,
    create_provider,
    default_registry,
    get_available_providers,
    register_provider,
)

if not default_registry.is_registered("openai"):
    default_registry.register("openai", OpenAIProvider)

if not default_registry.is_registered("gemini"):
    default_registry.register("gemini", GeminiProvider)

__all__ = [
    "GeminiProvider",
    "GeminiRequestFunction",
    "OpenAIProvider",
    "OpenAIRequestFunction",
    "ProviderRegistry",
    "create_provider",
    "default_registry",
    "get_available_providers",
    "register_provider",
]

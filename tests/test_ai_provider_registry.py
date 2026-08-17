import pytest

from ai_asset_platform.ai import ProviderRegistry


class FakeProvider:
    name = "fake-ai"

    def __init__(self, signal: str = "HOLD") -> None:
        self.signal = signal

    def evaluate(self, market_data):
        return {
            "signal": self.signal,
            "score": 50,
            "confidence": 50,
            "reason": "テスト用AI判定です。",
        }


def test_registry_registers_and_creates_provider():
    registry = ProviderRegistry()
    registry.register("fake", FakeProvider)

    provider = registry.create("fake", signal="BUY")

    assert provider.name == "fake-ai"
    assert provider.signal == "BUY"


def test_registry_normalizes_provider_name():
    registry = ProviderRegistry()
    registry.register("  FaKe  ", FakeProvider)

    assert registry.is_registered("fake")
    assert registry.is_registered("FAKE")
    assert registry.available_providers() == ("fake",)


def test_registry_rejects_duplicate_registration():
    registry = ProviderRegistry()
    registry.register("fake", FakeProvider)

    with pytest.raises(ValueError, match="登録済み"):
        registry.register("fake", FakeProvider)


def test_registry_can_replace_registered_provider():
    class ReplacementProvider(FakeProvider):
        name = "replacement-ai"

    registry = ProviderRegistry()
    registry.register("fake", FakeProvider)
    registry.register("fake", ReplacementProvider, replace=True)

    provider = registry.create("fake")

    assert provider.name == "replacement-ai"


def test_registry_reports_unknown_provider():
    registry = ProviderRegistry()

    with pytest.raises(ValueError, match="未登録"):
        registry.create("openai")


def test_registry_unregisters_provider():
    registry = ProviderRegistry()
    registry.register("fake", FakeProvider)

    assert registry.unregister("fake") is True
    assert registry.unregister("fake") is False
    assert registry.available_providers() == ()


def test_registry_rejects_invalid_provider_object():
    class InvalidProvider:
        name = "invalid"

    registry = ProviderRegistry()
    registry.register("invalid", InvalidProvider)

    with pytest.raises(TypeError, match="evaluate"):
        registry.create("invalid")

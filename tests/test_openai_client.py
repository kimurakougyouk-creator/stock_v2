import pytest

from ai_asset_platform.ai.openai_client import OpenAIClient


class FakeResponse:
    def __init__(self, output_text):
        self.output_text = output_text


class FakeResponses:
    def __init__(self, output_text=None, error=None):
        self.output_text = output_text
        self.error = error
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)

        if self.error is not None:
            raise self.error

        return FakeResponse(self.output_text)


class FakeOpenAI:
    def __init__(self, output_text=None, error=None):
        self.responses = FakeResponses(
            output_text=output_text,
            error=error,
        )


def test_openai_client_rejects_empty_api_key():
    with pytest.raises(ValueError, match="APIキー"):
        OpenAIClient(api_key="   ")


def test_openai_client_rejects_invalid_timeout():
    with pytest.raises(ValueError, match="timeout"):
        OpenAIClient(api_key="test-key", timeout=0)


def test_openai_client_calls_responses_api():
    fake_client = FakeOpenAI(
        output_text=(
            '{"signal":"BUY","score":85,'
            '"confidence":90,"reason":"上昇傾向"}'
        )
    )

    client = OpenAIClient(
        api_key="test-key",
        client=fake_client,
    )

    result = client.request(
        "test-model",
        "system instruction",
        {"prompt": "market information"},
    )

    assert result["signal"] == "BUY"

    call = fake_client.responses.calls[0]

    assert call["model"] == "test-model"
    assert call["instructions"] == "system instruction"
    assert call["input"] == "market information"


def test_openai_client_rejects_empty_model():
    client = OpenAIClient(
        api_key="test-key",
        client=FakeOpenAI(),
    )

    with pytest.raises(ValueError, match="モデル名"):
        client.request(
            "   ",
            "system",
            {"prompt": "market"},
        )


def test_openai_client_rejects_invalid_payload():
    client = OpenAIClient(
        api_key="test-key",
        client=FakeOpenAI(),
    )

    with pytest.raises(TypeError, match="辞書形式"):
        client.request(
            "test-model",
            "system",
            ["market"],
        )


def test_openai_client_rejects_empty_prompt():
    client = OpenAIClient(
        api_key="test-key",
        client=FakeOpenAI(),
    )

    with pytest.raises(ValueError, match="プロンプト"):
        client.request(
            "test-model",
            "system",
            {"prompt": "   "},
        )


def test_openai_client_handles_api_error():
    client = OpenAIClient(
        api_key="test-key",
        client=FakeOpenAI(error=RuntimeError("network error")),
    )

    with pytest.raises(RuntimeError, match="API通信"):
        client.request(
            "test-model",
            "system",
            {"prompt": "market"},
        )


def test_openai_client_rejects_empty_response():
    client = OpenAIClient(
        api_key="test-key",
        client=FakeOpenAI(output_text=""),
    )

    with pytest.raises(RuntimeError, match="空の応答"):
        client.request(
            "test-model",
            "system",
            {"prompt": "market"},
        )


def test_openai_client_rejects_invalid_json():
    client = OpenAIClient(
        api_key="test-key",
        client=FakeOpenAI(output_text="BUY"),
    )

    with pytest.raises(ValueError, match="JSON"):
        client.request(
            "test-model",
            "system",
            {"prompt": "market"},
        )


def test_openai_client_rejects_non_mapping_json():
    client = OpenAIClient(
        api_key="test-key",
        client=FakeOpenAI(output_text='["BUY"]'),
    )

    with pytest.raises(TypeError, match="辞書形式"):
        client.request(
            "test-model",
            "system",
            {"prompt": "market"},
        )

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from ..openai_client import OpenAIClient


OpenAIRequestFunction = Callable[
    [str, str, Mapping[str, Any]],
    Mapping[str, Any],
]


class OpenAIProvider:
    """OpenAIを利用して市場情報を評価するAIプロバイダー。"""

    name = "openai"

    def __init__(
        self,
        *,
        model: str = "gpt-4.1-mini",
        api_key: str = "",
        timeout: float = 30.0,
        request_function: OpenAIRequestFunction | None = None,
        client: Any | None = None,
    ) -> None:
        normalized_model = str(model or "").strip()
        normalized_api_key = str(api_key or "").strip()

        if not normalized_model:
            raise ValueError("OpenAIのモデル名を指定してください。")

        self.model = normalized_model
        self.api_key = normalized_api_key
        self.timeout = float(timeout)
        self.request_function = request_function
        self.openai_client: OpenAIClient | None = None

        if self.request_function is None and self.api_key:
            self.openai_client = OpenAIClient(
                api_key=self.api_key,
                timeout=self.timeout,
                client=client,
            )
            self.request_function = self.openai_client.request

    @staticmethod
    def build_system_prompt() -> str:
        """OpenAIへ渡す基本指示を作成する。"""

        return (
            "あなたは金融市場を慎重に評価するAI Judgeです。"
            "提供された市場情報のみを使用し、"
            "BUY、SELL、HOLDのいずれかを判定してください。"
            "必ずJSON形式でsignal、score、confidence、reasonを返してください。"
            "signalはBUY、SELL、HOLDのいずれかにしてください。"
            "scoreとconfidenceは0から100の範囲にしてください。"
            "情報が不足している場合はHOLDを選択してください。"
            "JSON以外の文章やコードブロックは付けないでください。"
        )

    @staticmethod
    def build_user_prompt(market_data: Mapping[str, Any]) -> str:
        """市場情報をOpenAI用の文章へ変換する。"""

        if not isinstance(market_data, Mapping):
            raise TypeError("market_dataは辞書形式で指定してください。")

        if not market_data:
            return "市場情報は提供されていません。"

        lines = ["以下の市場情報を評価してください。"]

        for key in sorted(market_data, key=str):
            lines.append(f"- {key}: {market_data[key]}")

        return "\n".join(lines)

    def evaluate(
        self,
        market_data: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        """市場情報をOpenAIで評価する。"""

        if self.request_function is None:
            raise RuntimeError(
                "OpenAI通信機能が未設定です。"
                "API接続を設定するまでは安全なHOLDを使用します。"
            )

        system_prompt = self.build_system_prompt()
        user_prompt = self.build_user_prompt(market_data)

        response = self.request_function(
            self.model,
            system_prompt,
            {
                "prompt": user_prompt,
                "market_data": dict(market_data),
            },
        )

        if not isinstance(response, Mapping):
            raise TypeError(
                "OpenAIの評価結果は辞書形式である必要があります。"
            )

        return response

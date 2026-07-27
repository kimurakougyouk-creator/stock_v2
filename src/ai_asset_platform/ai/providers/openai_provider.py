from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any


OpenAIRequestFunction = Callable[
    [str, str, Mapping[str, Any]],
    Mapping[str, Any],
]


class OpenAIProvider:
    """
    OpenAIを利用するAIプロバイダーの基本クラス。

    現段階ではOpenAI APIへ直接通信せず、
    request_functionとして外部から通信処理を受け取る。
    """

    name = "openai"

    def __init__(
        self,
        *,
        model: str = "gpt-4.1-mini",
        request_function: OpenAIRequestFunction | None = None,
    ) -> None:
        normalized_model = str(model or "").strip()

        if not normalized_model:
            raise ValueError("OpenAIのモデル名を指定してください。")

        self.model = normalized_model
        self.request_function = request_function

    @staticmethod
    def build_system_prompt() -> str:
        """OpenAIへ渡す基本指示を作成する。"""

        return (
            "あなたは金融市場を慎重に評価するAI Judgeです。"
            "提供された市場情報のみを使用し、"
            "BUY、SELL、HOLDのいずれかを判定してください。"
            "必ずsignal、score、confidence、reasonを返してください。"
            "scoreとconfidenceは0から100の範囲にしてください。"
            "情報が不足している場合はHOLDを選択してください。"
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
        """
        市場情報をOpenAIで評価する。

        現段階ではrequest_functionが未設定の場合、
        通信せずにエラーを返す。
        AI Judge側がこのエラーを安全なHOLDへ変換する。
        """

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

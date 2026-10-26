from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from ..gemini_client import GeminiClient


GeminiRequestFunction = Callable[
    [str, str, Mapping[str, Any]],
    Mapping[str, Any],
]

# AISettings.gemini_model's own default when GEMINI_MODEL is unset. It is
# not a real Gemini model id; sending it to the API would 404, and
# judge_with_ai() would silently swallow that into a generic HOLD, hiding
# the misconfiguration from whoever set GEMINI_API_KEY expecting it to work.
_PLACEHOLDER_MODEL = "gemini-default"


class GeminiProvider:
    """
    Google Geminiを利用するAIプロバイダー。

    api_keyが指定された場合はGeminiClient(urllibのみを使う
    REST実装、新規の外部パッケージ依存なし)を自動的に構築する。
    request_functionを明示的に渡した場合はそれを優先する(テスト用)。
    """

    name = "gemini"

    def __init__(
        self,
        *,
        model: str = "gemini-default",
        api_key: str = "",
        timeout: float = 30.0,
        request_function: GeminiRequestFunction | None = None,
        opener: Any | None = None,
        max_output_tokens: int | None = 512,
        thinking_level: str | None = "low",
    ) -> None:
        normalized_model = str(model or "").strip()

        if not normalized_model:
            raise ValueError("Geminiのモデル名を指定してください。")

        self.model = normalized_model
        self.api_key = str(api_key or "").strip()
        self.timeout = float(timeout)
        self.request_function = request_function
        self.gemini_client: GeminiClient | None = None

        if self.request_function is None and self.api_key:
            if self.model == _PLACEHOLDER_MODEL:
                raise ValueError(
                    "GeminiのモデルIDをGEMINI_MODELで明示的に指定してください。"
                    f"「{_PLACEHOLDER_MODEL}」は実在するモデルIDではなく、"
                    "未設定時の既定値です。"
                )
            self.gemini_client = GeminiClient(
                api_key=self.api_key,
                timeout=self.timeout,
                opener=opener,
                max_output_tokens=max_output_tokens,
                thinking_level=thinking_level,
            )
            self.request_function = self.gemini_client.request

    @staticmethod
    def build_system_prompt() -> str:
        """Geminiへ渡す基本指示を作成する。"""

        return (
            "あなたは金融市場を慎重に評価するAI Judgeです。"
            "提供された市場情報だけを使用して、"
            "BUY、SELL、HOLDのいずれかを判定してください。"
            "必ずsignal、score、confidence、reasonを返してください。"
            "scoreとconfidenceは0から100の範囲にしてください。"
            "情報不足、判断困難、矛盾がある場合はHOLDを選択してください。"
        )

    @staticmethod
    def build_user_prompt(market_data: Mapping[str, Any]) -> str:
        """市場情報をGemini用の文章へ変換する。"""

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
        市場情報をGeminiで評価する。

        request_functionが未設定の場合は通信せずにエラーを返す。
        AI Judge側がこのエラーを安全なHOLDへ変換する。
        """

        if self.request_function is None:
            raise RuntimeError(
                "Gemini通信機能が未設定です。"
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
                "Geminiの評価結果は辞書形式である必要があります。"
            )

        return response

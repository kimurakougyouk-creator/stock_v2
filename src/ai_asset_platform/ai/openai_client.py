from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any


class OpenAIClient:
    """OpenAI Responses APIとの通信を担当するクライアント。"""

    def __init__(
        self,
        *,
        api_key: str,
        timeout: float = 30.0,
        client: Any | None = None,
    ) -> None:
        normalized_api_key = str(api_key or "").strip()

        if not normalized_api_key:
            raise ValueError("OpenAI APIキーを指定してください。")

        if timeout <= 0:
            raise ValueError("timeoutは0より大きい値を指定してください。")

        self.api_key = normalized_api_key
        self.timeout = float(timeout)

        if client is None:
            from openai import OpenAI

            client = OpenAI(
                api_key=self.api_key,
                timeout=self.timeout,
            )

        self.client = client

    def request(
        self,
        model: str,
        system_prompt: str,
        payload: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        """OpenAIへ評価を依頼し、辞書形式の結果を返す。"""

        normalized_model = str(model or "").strip()

        if not normalized_model:
            raise ValueError("OpenAIのモデル名を指定してください。")

        if not isinstance(payload, Mapping):
            raise TypeError("payloadは辞書形式で指定してください。")

        user_prompt = str(payload.get("prompt") or "").strip()

        if not user_prompt:
            raise ValueError("OpenAIへ送るプロンプトが空です。")

        try:
            response = self.client.responses.create(
                model=normalized_model,
                instructions=str(system_prompt or "").strip(),
                input=user_prompt,
            )
        except Exception as exc:
            raise RuntimeError(
                f"OpenAI API通信に失敗しました: {exc}"
            ) from exc

        output_text = str(
            getattr(response, "output_text", "") or ""
        ).strip()

        if not output_text:
            raise RuntimeError("OpenAIから空の応答が返されました。")

        try:
            result = json.loads(output_text)
        except json.JSONDecodeError as exc:
            raise ValueError(
                "OpenAIの応答をJSONとして解析できませんでした。"
            ) from exc

        if not isinstance(result, Mapping):
            raise TypeError(
                "OpenAIの応答は辞書形式である必要があります。"
            )

        return dict(result)

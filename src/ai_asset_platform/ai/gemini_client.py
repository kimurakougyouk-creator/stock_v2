from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Mapping
from typing import Any, Callable


DEFAULT_GEMINI_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models"

Opener = Callable[..., Any]


class GeminiClient:
    """Google Gemini generateContent REST APIとの通信を担当するクライアント。

    標準ライブラリのurllibのみを使用し、新規の外部依存を追加しない。
    APIキーはURLのクエリパラメータではなく、`x-goog-api-key`ヘッダーで送る。
    これにより、通信失敗時の例外メッセージやURLログにキーが混入しない。
    """

    def __init__(
        self,
        *,
        api_key: str,
        timeout: float = 30.0,
        endpoint: str = DEFAULT_GEMINI_ENDPOINT,
        opener: Opener | None = None,
        max_output_tokens: int | None = 512,
        thinking_level: str | None = "low",
    ) -> None:
        normalized_api_key = str(api_key or "").strip()

        if not normalized_api_key:
            raise ValueError("Gemini APIキーを指定してください。")

        if timeout <= 0:
            raise ValueError("timeoutは0より大きい値を指定してください。")

        if max_output_tokens is not None and max_output_tokens <= 0:
            raise ValueError("max_output_tokensは0より大きい値を指定してください。")

        self.api_key = normalized_api_key
        self.timeout = float(timeout)
        self.endpoint = str(endpoint or DEFAULT_GEMINI_ENDPOINT).rstrip("/")
        self._opener: Opener = opener or urllib.request.urlopen
        # AI Judgeは短い構造化JSON(signal/score/confidence/reason)だけを
        # 必要とする単発分類タスクであり、長文生成や深い推論は不要。
        # これらを未設定のままにすると、thinkingモデル(例: gemini-3.8-flash)が
        # 無制限に内部思考トークンを消費し、応答が極端に遅くなる(タイムアウト超過)
        # 余地を残す。両方とも安全側のデフォルトで明示的に制限する。
        self.max_output_tokens = (
            int(max_output_tokens) if max_output_tokens is not None else None
        )
        self.thinking_level = (
            str(thinking_level).strip() if thinking_level else None
        )

    def request(
        self,
        model: str,
        system_prompt: str,
        payload: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        """Geminiへ評価を依頼し、辞書形式の結果を返す。"""

        normalized_model = str(model or "").strip()

        if not normalized_model:
            raise ValueError("Geminiのモデル名を指定してください。")

        if not isinstance(payload, Mapping):
            raise TypeError("payloadは辞書形式で指定してください。")

        user_prompt = str(payload.get("prompt") or "").strip()

        if not user_prompt:
            raise ValueError("Geminiへ送るプロンプトが空です。")

        url = f"{self.endpoint}/{normalized_model}:generateContent"
        generation_config: dict[str, Any] = {"responseMimeType": "application/json"}
        if self.max_output_tokens is not None:
            generation_config["maxOutputTokens"] = self.max_output_tokens
        if self.thinking_level is not None:
            generation_config["thinkingConfig"] = {
                "thinkingLevel": self.thinking_level,
            }
        body = json.dumps(
            {
                "systemInstruction": {
                    "parts": [{"text": str(system_prompt or "").strip()}],
                },
                "contents": [{"parts": [{"text": user_prompt}]}],
                "generationConfig": generation_config,
            }
        ).encode("utf-8")

        request = urllib.request.Request(
            url,
            data=body,
            headers={
                "Content-Type": "application/json",
                "x-goog-api-key": self.api_key,
            },
            method="POST",
        )

        try:
            with self._opener(request, timeout=self.timeout) as response:
                raw = response.read()
        except urllib.error.HTTPError as exc:
            try:
                detail = exc.read().decode("utf-8", errors="replace")
            except Exception:
                detail = str(exc)
            raise RuntimeError(
                f"Gemini API通信に失敗しました: HTTP {exc.code} {detail}"
            ) from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Gemini API通信に失敗しました: {exc.reason}") from exc

        try:
            decoded = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError(
                "Geminiの応答をJSONとして解析できませんでした。"
            ) from exc

        try:
            candidates = decoded["candidates"]
            output_text = candidates[0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError(
                "Geminiの応答形式が想定と異なります。"
            ) from exc

        output_text = str(output_text or "").strip()

        if not output_text:
            raise RuntimeError("Geminiから空の応答が返されました。")

        try:
            result = json.loads(output_text)
        except json.JSONDecodeError as exc:
            raise ValueError(
                "Geminiの応答をJSONとして解析できませんでした。"
            ) from exc

        if not isinstance(result, Mapping):
            raise TypeError("Geminiの応答は辞書形式である必要があります。")

        return dict(result)

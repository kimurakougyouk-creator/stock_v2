from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol


VALID_SIGNALS = {"BUY", "SELL", "HOLD"}


@dataclass(frozen=True)
class AIJudgeResult:
    """AIによる売買評価結果。"""

    signal: str
    score: float
    confidence: float
    reason: str
    provider: str
    available: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "signal": self.signal,
            "score": self.score,
            "confidence": self.confidence,
            "reason": self.reason,
            "provider": self.provider,
            "available": self.available,
        }


class AIProvider(Protocol):
    """GPTやGeminiなどのAI接続先が実装する共通形式。"""

    name: str

    def evaluate(self, market_data: Mapping[str, Any]) -> Mapping[str, Any]:
        ...


def _normalize_signal(value: Any) -> str:
    signal = str(value or "HOLD").strip().upper()
    return signal if signal in VALID_SIGNALS else "HOLD"


def _normalize_score(value: Any, default: float = 50.0) -> float:
    try:
        score = float(value)
    except (TypeError, ValueError):
        score = default

    return max(0.0, min(100.0, score))


def _normalize_confidence(value: Any, default: float = 0.0) -> float:
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        confidence = default

    return max(0.0, min(100.0, confidence))


def create_safe_fallback(
    reason: str = "AIが未設定のため、安全側でHOLDとします。",
) -> AIJudgeResult:
    """AIが使えない場合の安全な初期結果を返す。"""

    return AIJudgeResult(
        signal="HOLD",
        score=50.0,
        confidence=0.0,
        reason=reason,
        provider="none",
        available=False,
    )


def judge_with_ai(
    market_data: Mapping[str, Any],
    provider: AIProvider | None = None,
) -> AIJudgeResult:
    """
    AIプロバイダーを使って市場データを評価する。

    AIが未設定またはエラーの場合は、安全なHOLDを返す。
    """
    if provider is None:
        return create_safe_fallback()

    try:
        raw_result = provider.evaluate(market_data)
    except Exception as exc:
        return create_safe_fallback(
            f"AI評価中にエラーが発生したため、安全側でHOLDとします。{exc}"
        )

    if not isinstance(raw_result, Mapping):
        return create_safe_fallback(
            "AI評価結果の形式が不正なため、安全側でHOLDとします。"
        )

    signal = _normalize_signal(raw_result.get("signal"))
    score = _normalize_score(raw_result.get("score"))
    confidence = _normalize_confidence(raw_result.get("confidence"))
    reason = str(
        raw_result.get("reason")
        or "AIから判定理由が返されませんでした。"
    )

    return AIJudgeResult(
        signal=signal,
        score=score,
        confidence=confidence,
        reason=reason,
        provider=str(getattr(provider, "name", "unknown")),
        available=True,
    )

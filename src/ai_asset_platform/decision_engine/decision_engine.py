from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


VALID_SIGNALS = {"BUY", "SELL", "HOLD"}


@dataclass(frozen=True)
class DecisionResult:
    """テクニカル分析とAI評価を統合した最終判断結果。"""

    signal: str
    score: float
    confidence: float
    reason: str
    technical_signal: str
    technical_score: float
    ai_signal: str | None = None
    ai_score: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "signal": self.signal,
            "score": self.score,
            "confidence": self.confidence,
            "reason": self.reason,
            "technical_signal": self.technical_signal,
            "technical_score": self.technical_score,
            "ai_signal": self.ai_signal,
            "ai_score": self.ai_score,
        }


def _normalize_signal(value: Any) -> str:
    signal = str(value or "HOLD").upper()
    return signal if signal in VALID_SIGNALS else "HOLD"


def _normalize_score(value: Any, default: float = 50.0) -> float:
    try:
        score = float(value)
    except (TypeError, ValueError):
        score = default

    return max(0.0, min(100.0, score))


def _signal_strength(signal: str, score: float) -> float:
    """
    BUYはプラス、SELLはマイナス、HOLDは0として扱う。

    スコア50を中立とし、0～100点を-1～1へ変換する。
    """
    normalized = (score - 50.0) / 50.0

    if signal == "BUY":
        return abs(normalized) if normalized != 0 else 0.5

    if signal == "SELL":
        return -abs(normalized) if normalized != 0 else -0.5

    return 0.0


def combine_decisions(
    technical_result: Mapping[str, Any],
    ai_result: Mapping[str, Any] | None = None,
    technical_weight: float = 0.7,
    ai_weight: float = 0.3,
) -> DecisionResult:
    """
    テクニカル判定とAI判定を統合する。

    AI判定がない場合は、テクニカル判定をそのまま採用する。
    """
    if technical_weight < 0 or ai_weight < 0:
        raise ValueError("重みは0以上で指定してください。")

    technical_signal = _normalize_signal(technical_result.get("signal"))
    technical_score = _normalize_score(technical_result.get("score"))
    technical_reason = str(
        technical_result.get("reason") or "テクニカル判定理由はありません。"
    )

    if ai_result is None:
        confidence = abs(technical_score - 50.0) * 2.0
        return DecisionResult(
            signal=technical_signal,
            score=technical_score,
            confidence=round(confidence, 1),
            reason=f"AI評価なし｜{technical_reason}",
            technical_signal=technical_signal,
            technical_score=technical_score,
        )

    ai_signal = _normalize_signal(ai_result.get("signal"))
    ai_score = _normalize_score(ai_result.get("score"))
    ai_reason = str(ai_result.get("reason") or "AI判定理由はありません。")

    total_weight = technical_weight + ai_weight
    if total_weight <= 0:
        raise ValueError("重みの合計は0より大きくしてください。")

    technical_strength = _signal_strength(technical_signal, technical_score)
    ai_strength = _signal_strength(ai_signal, ai_score)

    combined_strength = (
        technical_strength * technical_weight
        + ai_strength * ai_weight
    ) / total_weight

    if combined_strength > 0.2:
        final_signal = "BUY"
    elif combined_strength < -0.2:
        final_signal = "SELL"
    else:
        final_signal = "HOLD"

    final_score = (combined_strength + 1.0) * 50.0
    final_score = max(0.0, min(100.0, final_score))
    confidence = min(100.0, abs(combined_strength) * 100.0)

    reason = (
        f"テクニカル評価: {technical_signal}・{technical_score:.1f}点"
        f"｜AI評価: {ai_signal}・{ai_score:.1f}点"
        f"｜{technical_reason}"
        f"｜{ai_reason}"
    )

    return DecisionResult(
        signal=final_signal,
        score=round(final_score, 1),
        confidence=round(confidence, 1),
        reason=reason,
        technical_signal=technical_signal,
        technical_score=technical_score,
        ai_signal=ai_signal,
        ai_score=ai_score,
    )

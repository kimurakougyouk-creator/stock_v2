from __future__ import annotations

from dataclasses import dataclass

from ai_asset_platform.ai import AIJudgeResult


VALID_SIGNALS = {"BUY", "SELL", "HOLD"}


@dataclass(frozen=True)
class FinalDecisionResult:
    """テクニカル分析とAI評価を統合した最終判定結果。"""

    signal: str
    reason: str
    technical_signal: str
    ai_signal: str
    ai_confidence: float
    ai_available: bool


def determine_final_decision(
    technical_signal: str,
    ai_result: AIJudgeResult,
    *,
    minimum_ai_confidence: float = 70.0,
) -> FinalDecisionResult:
    """
    テクニカル判定とAI判定から、実際に使用する最終シグナルを決める。

    安全ルール:
    - AIが利用できない場合はHOLD
    - AI信頼度が基準未満の場合はHOLD
    - テクニカルとAIが一致しない場合はHOLD
    - BUYまたはSELLが一致した場合だけ、その判定を採用する
    """

    normalized_technical_signal = str(
        technical_signal or "HOLD"
    ).strip().upper()

    if normalized_technical_signal not in VALID_SIGNALS:
        normalized_technical_signal = "HOLD"

    ai_signal = str(ai_result.signal or "HOLD").strip().upper()

    if ai_signal not in VALID_SIGNALS:
        ai_signal = "HOLD"

    if not ai_result.available:
        return FinalDecisionResult(
            signal="HOLD",
            reason="AIを利用できないため、安全側でHOLDとします。",
            technical_signal=normalized_technical_signal,
            ai_signal=ai_signal,
            ai_confidence=float(ai_result.confidence),
            ai_available=False,
        )

    if float(ai_result.confidence) < minimum_ai_confidence:
        return FinalDecisionResult(
            signal="HOLD",
            reason=(
                f"AI信頼度が基準未満です。"
                f"信頼度={float(ai_result.confidence):.1f}%、"
                f"必要信頼度={minimum_ai_confidence:.1f}%"
            ),
            technical_signal=normalized_technical_signal,
            ai_signal=ai_signal,
            ai_confidence=float(ai_result.confidence),
            ai_available=True,
        )

    if normalized_technical_signal == "HOLD":
        return FinalDecisionResult(
            signal="HOLD",
            reason="テクニカル判定がHOLDのため、最終判定もHOLDです。",
            technical_signal=normalized_technical_signal,
            ai_signal=ai_signal,
            ai_confidence=float(ai_result.confidence),
            ai_available=True,
        )

    if ai_signal != normalized_technical_signal:
        return FinalDecisionResult(
            signal="HOLD",
            reason=(
                "テクニカル判定とAI判定が一致しないため、"
                "安全側でHOLDとします。"
            ),
            technical_signal=normalized_technical_signal,
            ai_signal=ai_signal,
            ai_confidence=float(ai_result.confidence),
            ai_available=True,
        )

    return FinalDecisionResult(
        signal=normalized_technical_signal,
        reason=(
            f"テクニカル判定とAI判定がともに"
            f"{normalized_technical_signal}で一致し、"
            f"AI信頼度も{float(ai_result.confidence):.1f}%あります。"
        ),
        technical_signal=normalized_technical_signal,
        ai_signal=ai_signal,
        ai_confidence=float(ai_result.confidence),
        ai_available=True,
    )

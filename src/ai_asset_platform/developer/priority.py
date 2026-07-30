from __future__ import annotations

from dataclasses import dataclass

from src.ai_asset_platform.developer.planner import DevelopmentPlan


@dataclass(frozen=True)
class DevelopmentPriority:
    """次に実装すべき開発候補。"""

    title: str
    target_file: str
    recommended_test: str
    score: int
    reasons: list[str]


def _calculate_target_score(target_file: str) -> tuple[int, list[str]]:
    """変更対象ファイルの重要度を点数化する。"""
    normalized = target_file.casefold()
    score = 0
    reasons: list[str] = []

    if "risk" in normalized:
        score += 50
        reasons.append("リスク管理は資金保護に直結する")

    if "execution" in normalized or "order" in normalized:
        score += 45
        reasons.append("注文処理は実運用の安全性に直結する")

    if "signal" in normalized:
        score += 40
        reasons.append("売買シグナルは取引判断の中心機能である")

    if "developer" in normalized:
        score += 35
        reasons.append("開発自動化は今後の作業効率を高める")

    if "report" in normalized:
        score += 25
        reasons.append("レポートは運用結果の検証に必要である")

    if "dashboard" in normalized:
        score += 20
        reasons.append("ダッシュボードは状況確認を効率化する")

    if "settings" in normalized:
        score += 15
        reasons.append("設定管理は保守性と安全性を高める")

    if not reasons:
        score += 10
        reasons.append("開発計画で変更対象として特定された")

    return score, reasons


def select_next_priority(
    plan: DevelopmentPlan,
) -> DevelopmentPriority:
    """開発計画から最優先の実装候補を1つ選ぶ。"""
    unknown_target = "開発指示を確認して変更対象を特定"
    unknown_test = "関連する既存テストを特定"

    if not plan.target_files or plan.target_files == [unknown_target]:
        return DevelopmentPriority(
            title="変更対象の確認",
            target_file=unknown_target,
            recommended_test=unknown_test,
            score=0,
            reasons=[
                "変更対象を自動特定できていないため、人の確認が必要"
            ],
        )

    priorities: list[DevelopmentPriority] = []

    for index, target_file in enumerate(plan.target_files):
        score, reasons = _calculate_target_score(target_file)

        if index < len(plan.recommended_tests):
            recommended_test = plan.recommended_tests[index]
        elif plan.recommended_tests:
            recommended_test = plan.recommended_tests[0]
        else:
            recommended_test = unknown_test

        priorities.append(
            DevelopmentPriority(
                title=f"{target_file} の改善",
                target_file=target_file,
                recommended_test=recommended_test,
                score=score,
                reasons=reasons,
            )
        )

    return max(
        priorities,
        key=lambda priority: priority.score,
    )

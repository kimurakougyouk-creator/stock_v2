from __future__ import annotations

from dataclasses import dataclass

from ai_asset_platform.developer.planner import DevelopmentPlan
from ai_asset_platform.developer.priority import DevelopmentPriority


READY_STATUS = "READY"


@dataclass(frozen=True)
class DevelopmentTask:
    """AI開発者が次に扱う実行タスク。"""

    title: str
    target_file: str
    recommended_test: str
    readiness: str
    priority_score: int
    executable: bool
    safety_checks: tuple[str, ...]
    reasons: tuple[str, ...]


def create_development_task(
    plan: DevelopmentPlan,
    priority: DevelopmentPriority,
    readiness: str,
) -> DevelopmentTask:
    """開発計画と優先順位から安全な実行タスクを作成する。"""
    normalized_readiness = readiness.strip().upper()

    return DevelopmentTask(
        title=priority.title,
        target_file=priority.target_file,
        recommended_test=priority.recommended_test,
        readiness=normalized_readiness,
        priority_score=priority.score,
        executable=(
            normalized_readiness == READY_STATUS
            and priority.score > 0
        ),
        safety_checks=tuple(plan.safety_checks),
        reasons=tuple(priority.reasons),
    )

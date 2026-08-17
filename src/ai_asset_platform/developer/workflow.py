from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ai_asset_platform.developer.file_analyzer import (
    FileAnalysis,
    analyze_task,
)
from ai_asset_platform.developer.planner import (
    DevelopmentPlan,
    create_plan,
)
from ai_asset_platform.developer.priority import (
    DevelopmentPriority,
    select_next_priority,
)
from ai_asset_platform.developer.task import (
    DevelopmentTask,
    create_development_task,
)


@dataclass(frozen=True)
class DevelopmentWorkflow:
    """AI開発者モードの実行結果"""

    plan: DevelopmentPlan
    priority: DevelopmentPriority
    task: DevelopmentTask
    analysis: FileAnalysis


def run_development_workflow(
    task_file: Path,
    readiness: str = "READY",
) -> DevelopmentWorkflow:
    """
    開発計画から実行タスク・対象ファイル解析までを
    一括実行する。
    """

    plan = create_plan(task_file)

    priority = select_next_priority(plan)

    task = create_development_task(
        plan=plan,
        priority=priority,
        readiness=readiness,
    )

    analysis = analyze_task(task)

    return DevelopmentWorkflow(
        plan=plan,
        priority=priority,
        task=task,
        analysis=analysis,
    )

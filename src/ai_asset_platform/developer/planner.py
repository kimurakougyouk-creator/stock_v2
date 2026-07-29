from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class DevelopmentPlan:
    title: str
    steps: list[str]


def create_plan(task_file: Path) -> DevelopmentPlan:
    """開発指示書からシンプルな実装計画を作成する。"""
    text = task_file.read_text(encoding="utf-8")

    title = "AI Development Plan"

    steps = [
        "開発指示書を確認",
        "変更対象を特定",
        "実装内容を整理",
        "テスト方針を決定",
    ]

    if "pytest" in text:
        steps.append("pytestを実行")

    if "Git" in text:
        steps.append("Git保存条件を確認")

    return DevelopmentPlan(
        title=title,
        steps=steps,
    )

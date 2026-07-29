from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class DevelopmentPlan:
    title: str
    steps: list[str]


CHECK_RULES: tuple[tuple[tuple[str, ...], str], ...] = (
    (("dashboard", "ダッシュボード"), "ダッシュボード表示を確認"),
    (("signal", "シグナル"), "シグナル判定を確認"),
    (("order", "注文", "発注"), "注文処理と安全制限を確認"),
    (("risk", "リスク"), "リスク管理と損失制限を確認"),
    (("setting", "settings", "設定"), "設定値と初期値を確認"),
    (("performance", "パフォーマンス", "成績"), "運用成績の計算を確認"),
    (("report", "レポート", "報告書"), "レポート生成を確認"),
)


def _append_unique(steps: list[str], step: str) -> None:
    """同じ確認項目を重複して追加しない。"""
    if step not in steps:
        steps.append(step)


def create_plan(task_file: Path) -> DevelopmentPlan:
    """開発指示書から実装計画と必要な確認項目を作成する。"""
    text = task_file.read_text(encoding="utf-8")
    normalized_text = text.casefold()

    title = "AI Development Plan"

    steps = [
        "開発指示書を確認",
        "変更対象を特定",
        "実装内容を整理",
        "テスト方針を決定",
    ]

    for keywords, check_step in CHECK_RULES:
        if any(keyword.casefold() in normalized_text for keyword in keywords):
            _append_unique(steps, check_step)

    if "pytest" in normalized_text or "test" in normalized_text or "テスト" in text:
        _append_unique(steps, "pytestを実行")

    if "git" in normalized_text:
        _append_unique(steps, "Git保存条件を確認")

    _append_unique(steps, "全テスト合格を確認")
    _append_unique(steps, "未保存の変更を確認")

    return DevelopmentPlan(
        title=title,
        steps=steps,
    )

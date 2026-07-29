from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class DevelopmentPlan:
    title: str
    steps: list[str]
    target_files: list[str]
    recommended_tests: list[str]
    safety_checks: list[str]


@dataclass(frozen=True)
class PlanningRule:
    keywords: tuple[str, ...]
    check_step: str
    target_files: tuple[str, ...]
    recommended_tests: tuple[str, ...]
    safety_checks: tuple[str, ...] = ()


PLANNING_RULES: tuple[PlanningRule, ...] = (
    PlanningRule(
        keywords=("dashboard", "ダッシュボード"),
        check_step="ダッシュボード表示を確認",
        target_files=("dashboard.py",),
        recommended_tests=(
            "tests/test_dashboard.py",
            "tests/test_dashboard_*.py",
        ),
    ),
    PlanningRule(
        keywords=("signal", "シグナル"),
        check_step="シグナル判定を確認",
        target_files=(
            "signal_runner.py",
            "src/ai_asset_platform/signals/",
        ),
        recommended_tests=(
            "tests/test_signal_engine.py",
            "tests/test_signal_runner*.py",
        ),
        safety_checks=(
            "BUY・SELL・HOLDの判定条件を確認",
        ),
    ),
    PlanningRule(
        keywords=("order", "注文", "発注"),
        check_step="注文処理と安全制限を確認",
        target_files=(
            "order_manager.py",
            "src/ai_asset_platform/execution/",
        ),
        recommended_tests=(
            "tests/test_order*.py",
            "tests/test_signal_runner_final_decision.py",
        ),
        safety_checks=(
            "実注文が無効の状態を維持",
            "注文数量と保有数量の制限を確認",
        ),
    ),
    PlanningRule(
        keywords=("risk", "リスク"),
        check_step="リスク管理と損失制限を確認",
        target_files=("risk_manager.py",),
        recommended_tests=("tests/test_risk_manager*.py",),
        safety_checks=(
            "損失上限とポジション上限を確認",
        ),
    ),
    PlanningRule(
        keywords=("setting", "settings", "設定"),
        check_step="設定値と初期値を確認",
        target_files=(
            "src/ai_asset_platform/core/settings.py",
            ".env.example",
        ),
        recommended_tests=(
            "tests/test_settings.py",
            "tests/test_ai_settings.py",
        ),
        safety_checks=(
            "APIキーなどの秘密情報を保存しない",
            "安全側の初期値を維持",
        ),
    ),
    PlanningRule(
        keywords=("performance", "パフォーマンス", "成績"),
        check_step="運用成績の計算を確認",
        target_files=(
            "src/ai_asset_platform/reports/",
            "dashboard.py",
        ),
        recommended_tests=(
            "tests/test_performance*.py",
            "tests/test_dashboard_performance*.py",
        ),
    ),
    PlanningRule(
        keywords=("report", "レポート", "報告書"),
        check_step="レポート生成を確認",
        target_files=(
            "src/ai_asset_platform/reports/",
            "results/",
        ),
        recommended_tests=(
            "tests/test_*report*.py",
        ),
        safety_checks=(
            "自動生成結果を不要にコミットしない",
        ),
    ),
    PlanningRule(
        keywords=("developer", "開発者", "自動開発", "planner", "計画"),
        check_step="AI開発者機能を確認",
        target_files=(
            "scripts/auto_developer.py",
            "src/ai_asset_platform/developer/",
        ),
        recommended_tests=(
            "tests/test_auto_developer.py",
            "tests/test_development_planner.py",
        ),
        safety_checks=(
            "main・masterブランチで自動変更しない",
            "自動コミットは実行しない",
        ),
    ),
)


def _append_unique(items: list[str], item: str) -> None:
    """同じ項目を重複して追加しない。"""
    if item not in items:
        items.append(item)


def _contains_keyword(text: str, keywords: tuple[str, ...]) -> bool:
    """開発指示に対象キーワードが含まれるか確認する。"""
    return any(keyword.casefold() in text for keyword in keywords)


def create_plan(task_file: Path) -> DevelopmentPlan:
    """開発指示書から実装計画と開発候補を作成する。"""
    text = task_file.read_text(encoding="utf-8")
    normalized_text = text.casefold()

    steps = [
        "開発指示書を確認",
        "変更対象を特定",
        "実装内容を整理",
        "テスト方針を決定",
    ]
    target_files: list[str] = []
    recommended_tests: list[str] = []
    safety_checks: list[str] = [
        "現在のブランチが保護ブランチではないことを確認",
        "作業開始前のGit状態を確認",
    ]

    for rule in PLANNING_RULES:
        if not _contains_keyword(normalized_text, rule.keywords):
            continue

        _append_unique(steps, rule.check_step)

        for target_file in rule.target_files:
            _append_unique(target_files, target_file)

        for test_file in rule.recommended_tests:
            _append_unique(recommended_tests, test_file)

        for safety_check in rule.safety_checks:
            _append_unique(safety_checks, safety_check)

    if (
        "pytest" in normalized_text
        or "test" in normalized_text
        or "テスト" in text
    ):
        _append_unique(steps, "pytestを実行")

    if "git" in normalized_text:
        _append_unique(steps, "Git保存条件を確認")

    if not target_files:
        target_files.append("開発指示を確認して変更対象を特定")

    if not recommended_tests:
        recommended_tests.append("関連する既存テストを特定")

    _append_unique(steps, "全テスト合格を確認")
    _append_unique(steps, "未保存の変更を確認")
    _append_unique(safety_checks, "全テスト合格後にGitへ保存")

    return DevelopmentPlan(
        title="AI Development Plan",
        steps=steps,
        target_files=target_files,
        recommended_tests=recommended_tests,
        safety_checks=safety_checks,
    )

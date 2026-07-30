from src.ai_asset_platform.developer.planner import DevelopmentPlan
from src.ai_asset_platform.developer.priority import (
    select_next_priority,
)


def _create_plan(
    target_files: list[str],
    recommended_tests: list[str],
) -> DevelopmentPlan:
    return DevelopmentPlan(
        title="AI Development Plan",
        steps=["開発指示書を確認"],
        target_files=target_files,
        recommended_tests=recommended_tests,
        safety_checks=["Git状態を確認"],
    )


def test_order_processing_is_prioritized_over_dashboard() -> None:
    plan = _create_plan(
        target_files=[
            "dashboard.py",
            "src/ai_asset_platform/execution/",
        ],
        recommended_tests=[
            "tests/test_dashboard.py",
            "tests/test_order*.py",
        ],
    )

    priority = select_next_priority(plan)

    assert priority.target_file == (
        "src/ai_asset_platform/execution/"
    )
    assert priority.score == 45
    assert "注文処理" in priority.reasons[0]


def test_risk_management_has_highest_priority() -> None:
    plan = _create_plan(
        target_files=[
            "dashboard.py",
            "risk_manager.py",
            "src/ai_asset_platform/reports/",
        ],
        recommended_tests=[
            "tests/test_dashboard.py",
            "tests/test_risk_manager*.py",
            "tests/test_performance*.py",
        ],
    )

    priority = select_next_priority(plan)

    assert priority.target_file == "risk_manager.py"
    assert priority.recommended_test == (
        "tests/test_risk_manager*.py"
    )
    assert priority.score == 50


def test_unknown_task_requires_manual_review() -> None:
    plan = _create_plan(
        target_files=[
            "開発指示を確認して変更対象を特定"
        ],
        recommended_tests=[
            "関連する既存テストを特定"
        ],
    )

    priority = select_next_priority(plan)

    assert priority.score == 0
    assert priority.title == "変更対象の確認"
    assert "人の確認が必要" in priority.reasons[0]


def test_developer_task_has_automation_priority() -> None:
    plan = _create_plan(
        target_files=[
            "src/ai_asset_platform/developer/",
        ],
        recommended_tests=[
            "tests/test_development_planner.py",
        ],
    )

    priority = select_next_priority(plan)

    assert priority.score == 35
    assert priority.target_file == (
        "src/ai_asset_platform/developer/"
    )

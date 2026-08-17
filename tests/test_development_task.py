from ai_asset_platform.developer.planner import DevelopmentPlan
from ai_asset_platform.developer.priority import DevelopmentPriority
from ai_asset_platform.developer.task import (
    create_development_task,
)


def _create_plan() -> DevelopmentPlan:
    return DevelopmentPlan(
        title="AI Development Plan",
        steps=["変更対象を確認"],
        target_files=["risk_manager.py"],
        recommended_tests=["tests/test_risk_manager*.py"],
        safety_checks=[
            "現在のブランチを確認",
            "全テスト合格後にGitへ保存",
        ],
    )


def _create_priority(
    *,
    score: int = 50,
) -> DevelopmentPriority:
    return DevelopmentPriority(
        title="risk_manager.py の改善",
        target_file="risk_manager.py",
        recommended_test="tests/test_risk_manager*.py",
        score=score,
        reasons=[
            "リスク管理は資金保護に直結する",
        ],
    )


def test_create_development_task_returns_executable_task() -> None:
    task = create_development_task(
        _create_plan(),
        _create_priority(),
        "READY",
    )

    assert task.title == "risk_manager.py の改善"
    assert task.target_file == "risk_manager.py"
    assert task.recommended_test == (
        "tests/test_risk_manager*.py"
    )
    assert task.readiness == "READY"
    assert task.priority_score == 50
    assert task.executable is True
    assert task.safety_checks == (
        "現在のブランチを確認",
        "全テスト合格後にGitへ保存",
    )
    assert task.reasons == (
        "リスク管理は資金保護に直結する",
    )


def test_review_required_task_is_not_executable() -> None:
    task = create_development_task(
        _create_plan(),
        _create_priority(),
        "REVIEW_REQUIRED",
    )

    assert task.readiness == "REVIEW_REQUIRED"
    assert task.executable is False


def test_zero_priority_task_is_not_executable() -> None:
    task = create_development_task(
        _create_plan(),
        _create_priority(score=0),
        "READY",
    )

    assert task.priority_score == 0
    assert task.executable is False


def test_readiness_is_normalized() -> None:
    task = create_development_task(
        _create_plan(),
        _create_priority(),
        " ready ",
    )

    assert task.readiness == "READY"
    assert task.executable is True

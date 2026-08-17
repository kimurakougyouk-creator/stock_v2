from pathlib import Path

from ai_asset_platform.developer.planner import create_plan


def _create_task(tmp_path: Path, text: str) -> Path:
    task = tmp_path / "development_task.md"
    task.write_text(text, encoding="utf-8")
    return task


def test_create_plan(tmp_path: Path) -> None:
    task = _create_task(tmp_path, "pytest\nGit\n")

    plan = create_plan(task)

    assert plan.title == "AI Development Plan"
    assert "pytestを実行" in plan.steps
    assert "Git保存条件を確認" in plan.steps
    assert "全テスト合格を確認" in plan.steps
    assert "未保存の変更を確認" in plan.steps


def test_dashboard_task_suggests_files_and_tests(
    tmp_path: Path,
) -> None:
    task = _create_task(
        tmp_path,
        "dashboardを改善してテストする",
    )

    plan = create_plan(task)

    assert "ダッシュボード表示を確認" in plan.steps
    assert "dashboard.py" in plan.target_files
    assert "tests/test_dashboard.py" in plan.recommended_tests


def test_order_task_adds_safety_checks(
    tmp_path: Path,
) -> None:
    task = _create_task(
        tmp_path,
        "注文と発注処理を改善する",
    )

    plan = create_plan(task)

    assert "注文処理と安全制限を確認" in plan.steps
    assert "実注文が無効の状態を維持" in plan.safety_checks
    assert (
        "注文数量と保有数量の制限を確認"
        in plan.safety_checks
    )


def test_developer_task_suggests_developer_files(
    tmp_path: Path,
) -> None:
    task = _create_task(
        tmp_path,
        "AI自動開発plannerを改善する",
    )

    plan = create_plan(task)

    assert (
        "scripts/auto_developer.py"
        in plan.target_files
    )
    assert (
        "tests/test_development_planner.py"
        in plan.recommended_tests
    )
    assert (
        "main・masterブランチで自動変更しない"
        in plan.safety_checks
    )


def test_unknown_task_uses_safe_fallback(
    tmp_path: Path,
) -> None:
    task = _create_task(
        tmp_path,
        "新しい機能を追加する",
    )

    plan = create_plan(task)

    assert plan.target_files == [
        "開発指示を確認して変更対象を特定"
    ]
    assert plan.recommended_tests == [
        "関連する既存テストを特定"
    ]


def test_plan_does_not_duplicate_items(
    tmp_path: Path,
) -> None:
    task = _create_task(
        tmp_path,
        "dashboard ダッシュボード order 注文 pytest test Git git",
    )

    plan = create_plan(task)

    assert plan.steps.count(
        "ダッシュボード表示を確認"
    ) == 1
    assert plan.steps.count(
        "注文処理と安全制限を確認"
    ) == 1
    assert plan.steps.count("pytestを実行") == 1
    assert plan.steps.count("Git保存条件を確認") == 1

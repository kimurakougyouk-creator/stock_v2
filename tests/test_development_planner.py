from pathlib import Path

from src.ai_asset_platform.developer.planner import create_plan


def _create_task(tmp_path: Path, text: str) -> Path:
    task = tmp_path / "development_task.md"
    task.write_text(text, encoding="utf-8")
    return task


def test_create_plan(tmp_path: Path) -> None:
    task = _create_task(
        tmp_path,
        "pytest\nGit\n",
    )

    plan = create_plan(task)

    assert plan.title == "AI Development Plan"
    assert "pytestを実行" in plan.steps
    assert "Git保存条件を確認" in plan.steps
    assert "全テスト合格を確認" in plan.steps
    assert "未保存の変更を確認" in plan.steps


def test_create_plan_adds_dashboard_check(tmp_path: Path) -> None:
    task = _create_task(
        tmp_path,
        "dashboardを改善する",
    )

    plan = create_plan(task)

    assert "ダッシュボード表示を確認" in plan.steps


def test_create_plan_adds_signal_and_order_checks(tmp_path: Path) -> None:
    task = _create_task(
        tmp_path,
        "シグナル判定と発注処理を改善する",
    )

    plan = create_plan(task)

    assert "シグナル判定を確認" in plan.steps
    assert "注文処理と安全制限を確認" in plan.steps


def test_create_plan_adds_risk_and_settings_checks(tmp_path: Path) -> None:
    task = _create_task(
        tmp_path,
        "risk管理とsettingsを変更する",
    )

    plan = create_plan(task)

    assert "リスク管理と損失制限を確認" in plan.steps
    assert "設定値と初期値を確認" in plan.steps


def test_create_plan_adds_performance_and_report_checks(
    tmp_path: Path,
) -> None:
    task = _create_task(
        tmp_path,
        "パフォーマンスレポートを追加する",
    )

    plan = create_plan(task)

    assert "運用成績の計算を確認" in plan.steps
    assert "レポート生成を確認" in plan.steps


def test_create_plan_does_not_duplicate_steps(tmp_path: Path) -> None:
    task = _create_task(
        tmp_path,
        "dashboard ダッシュボード test pytest Git git",
    )

    plan = create_plan(task)

    assert plan.steps.count("ダッシュボード表示を確認") == 1
    assert plan.steps.count("pytestを実行") == 1
    assert plan.steps.count("Git保存条件を確認") == 1

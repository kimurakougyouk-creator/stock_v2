from pathlib import Path

from src.ai_asset_platform.developer.planner import create_plan


def test_create_plan(tmp_path: Path) -> None:
    task = tmp_path / "development_task.md"
    task.write_text(
        "pytest\nGit\n",
        encoding="utf-8",
    )

    plan = create_plan(task)

    assert plan.title == "AI Development Plan"
    assert "pytestを実行" in plan.steps
    assert "Git保存条件を確認" in plan.steps

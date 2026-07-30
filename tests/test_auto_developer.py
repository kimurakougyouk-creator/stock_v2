from pathlib import Path

import pytest

import scripts.auto_developer as auto_developer
from scripts.auto_developer import (
    evaluate_readiness,
    load_task,
    save_status_report,
    validate_safe_branch,
)


def test_load_task_reads_instruction_file(tmp_path: Path) -> None:
    task_file = tmp_path / "development_task.md"
    task_file.write_text(
        "# AI自動開発タスク\n\n安全に開発する。",
        encoding="utf-8",
    )

    result = load_task(task_file)

    assert "AI自動開発タスク" in result
    assert "安全に開発する" in result


def test_load_task_rejects_missing_file(tmp_path: Path) -> None:
    task_file = tmp_path / "missing.md"

    with pytest.raises(FileNotFoundError):
        load_task(task_file)


def test_load_task_rejects_empty_file(tmp_path: Path) -> None:
    task_file = tmp_path / "development_task.md"
    task_file.write_text("", encoding="utf-8")

    with pytest.raises(ValueError):
        load_task(task_file)


@pytest.mark.parametrize("branch", ["main", "master"])
def test_validate_safe_branch_rejects_protected_branch(
    branch: str,
) -> None:
    with pytest.raises(RuntimeError):
        validate_safe_branch(branch)


def test_validate_safe_branch_accepts_version_branch() -> None:
    validate_safe_branch("version-7.7")


def test_save_status_report_writes_plan_file(
    tmp_path: Path,
) -> None:
    output_file = (
        tmp_path
        / ".ai_developer"
        / "development_plan.md"
    )
    report = (
        "AI Development Plan\n"
        "1. 開発指示書を確認"
    )

    saved_file = save_status_report(
        report,
        output_file,
    )

    assert saved_file == output_file
    assert output_file.read_text(
        encoding="utf-8",
    ) == report + "\n"


def test_status_report_shows_suggestions(
    tmp_path: Path,
    monkeypatch,
) -> None:
    task_file = tmp_path / "development_task.md"
    task_file.write_text(
        "dashboardと注文処理を改善してpytestを実行する",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        auto_developer,
        "TASK_FILE",
        task_file,
    )
    monkeypatch.setattr(
        auto_developer,
        "PROJECT_DIR",
        tmp_path,
    )
    monkeypatch.setattr(
        auto_developer,
        "get_current_branch",
        lambda: "version-7.7",
    )
    monkeypatch.setattr(
        auto_developer,
        "get_git_status",
        lambda: "変更なし",
    )

    report = auto_developer.create_status_report()

    assert "変更候補ファイル:" in report
    assert "- dashboard.py" in report
    assert "推奨テスト:" in report
    assert "- tests/test_dashboard.py" in report
    assert "安全確認:" in report
    assert "- 実注文が無効の状態を維持" in report
    assert "実行準備度: READY" in report
    assert "判定理由:" in report

def test_evaluate_readiness_returns_ready() -> None:
    readiness, reasons = evaluate_readiness(
        "変更なし",
        ["dashboard.py"],
        ["tests/test_dashboard.py"],
    )

    assert readiness == "READY"
    assert "未保存の変更なし" in reasons


def test_evaluate_readiness_requires_review_for_changes() -> None:
    readiness, reasons = evaluate_readiness(
        "M dashboard.py",
        ["dashboard.py"],
        ["tests/test_dashboard.py"],
    )

    assert readiness == "REVIEW_REQUIRED"
    assert (
        "未保存の変更があるため、内容確認が必要"
        in reasons
    )


def test_evaluate_readiness_requires_review_for_unknown_task() -> None:
    readiness, reasons = evaluate_readiness(
        "変更なし",
        ["開発指示を確認して変更対象を特定"],
        ["関連する既存テストを特定"],
    )

    assert readiness == "REVIEW_REQUIRED"
    assert (
        "変更対象ファイルを自動特定できていない"
        in reasons
    )
    assert (
        "実行するテストを自動特定できていない"
        in reasons
    )


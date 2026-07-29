from pathlib import Path

import pytest

from scripts.auto_developer import (
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
    validate_safe_branch("version-7.3")


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

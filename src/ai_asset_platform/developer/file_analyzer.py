from __future__ import annotations

from dataclasses import dataclass

from src.ai_asset_platform.developer.task import DevelopmentTask


@dataclass(frozen=True)
class FileAnalysis:
    """実装対象ファイルの解析結果。"""

    primary_target: str
    related_files: tuple[str, ...]


def analyze_task(task: DevelopmentTask) -> FileAnalysis:
    """実行タスクから変更候補ファイルを返す。"""

    related: list[str] = [task.target_file]

    normalized = task.target_file.casefold()

    if "developer" in normalized:
        related.append("tests/")
    elif "dashboard" in normalized:
        related.append("dashboard.py")
        related.append("tests/")
    elif "report" in normalized:
        related.append("results/")
        related.append("tests/")
    else:
        related.append("tests/")

    return FileAnalysis(
        primary_target=task.target_file,
        related_files=tuple(dict.fromkeys(related)),
    )

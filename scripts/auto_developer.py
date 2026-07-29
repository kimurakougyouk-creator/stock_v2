#!/usr/bin/env python3
"""AI自動開発エージェントの安全な土台。"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parent.parent

project_dir_text = str(PROJECT_DIR)
if project_dir_text not in sys.path:
    sys.path.insert(0, project_dir_text)

from src.ai_asset_platform.developer.planner import create_plan


TASK_FILE = PROJECT_DIR / "development_task.md"
PLAN_FILE = PROJECT_DIR / ".ai_developer" / "development_plan.md"
PROTECTED_BRANCHES = {"main", "master"}


def run_git(*args: str) -> str:
    """Gitコマンドを実行して結果を返す。"""
    result = subprocess.run(
        ["git", *args],
        cwd=PROJECT_DIR,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def load_task(task_file: Path = TASK_FILE) -> str:
    """開発指示書を読み込む。"""
    if not task_file.exists():
        raise FileNotFoundError(
            f"開発指示書が見つかりません: {task_file}"
        )

    task = task_file.read_text(encoding="utf-8").strip()

    if not task:
        raise ValueError("開発指示書が空です。")

    return task


def get_current_branch() -> str:
    """現在のGitブランチ名を取得する。"""
    branch = run_git("branch", "--show-current")

    if not branch:
        raise RuntimeError("現在のGitブランチを確認できません。")

    return branch


def validate_safe_branch(branch: str) -> None:
    """保護ブランチでの自動開発を禁止する。"""
    if branch in PROTECTED_BRANCHES:
        raise RuntimeError(
            f"保護ブランチ '{branch}' では自動開発できません。"
        )


def get_git_status() -> str:
    """現在の変更ファイルを取得する。"""
    status = run_git("status", "--short")
    return status or "変更なし"


def _numbered_lines(items: list[str]) -> list[str]:
    """項目を番号付きの表示へ変換する。"""
    return [
        f"{index}. {item}"
        for index, item in enumerate(items, start=1)
    ]


def _bullet_lines(items: list[str]) -> list[str]:
    """項目を箇条書き表示へ変換する。"""
    return [f"- {item}" for item in items]


def create_status_report() -> str:
    """自動開発開始前の安全確認結果を作る。"""
    task = load_task()
    branch = get_current_branch()
    validate_safe_branch(branch)
    status = get_git_status()
    plan = create_plan(TASK_FILE)

    return "\n".join(
        [
            "========================================",
            " AI自動開発エージェント 安全確認",
            "========================================",
            f"プロジェクト: {PROJECT_DIR}",
            f"現在のブランチ: {branch}",
            "",
            "変更ファイル:",
            status,
            "",
            "開発指示書:",
            task,
            "",
            "自動生成された実装計画:",
            plan.title,
            *_numbered_lines(plan.steps),
            "",
            "変更候補ファイル:",
            *_bullet_lines(plan.target_files),
            "",
            "推奨テスト:",
            *_bullet_lines(plan.recommended_tests),
            "",
            "安全確認:",
            *_bullet_lines(plan.safety_checks),
            "",
            "✅ 安全確認と実装計画の作成が完了しました。",
            "現在は計画作成モードです。",
            "コードの自動変更やGit保存はまだ行いません。",
        ]
    )


def save_status_report(
    report: str,
    output_file: Path = PLAN_FILE,
) -> Path:
    """自動生成した開発計画をファイルへ保存する。"""
    output_file.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    output_file.write_text(
        report.rstrip() + "\n",
        encoding="utf-8",
    )
    return output_file


def main() -> int:
    """コマンドライン実行処理。"""
    try:
        report = create_status_report()
        saved_file = save_status_report(report)

        print(report)
        print()
        print(f"開発計画を保存しました: {saved_file}")
    except (
        FileNotFoundError,
        ValueError,
        RuntimeError,
        OSError,
        subprocess.CalledProcessError,
    ) as error:
        print(f"エラー: {error}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

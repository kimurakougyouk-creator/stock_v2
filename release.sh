#!/usr/bin/env bash

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
PYTHON="$PROJECT_DIR/.venv/bin/python"

cd "$PROJECT_DIR"

echo
echo "========================================"
echo " AI Asset Platform リリース保存"
echo "========================================"

if [ ! -x "$PYTHON" ]; then
    echo "エラー: 仮想環境のPythonが見つかりません。"
    echo "確認場所: $PYTHON"
    exit 1
fi

BRANCH="$(git branch --show-current)"

if [ -z "$BRANCH" ]; then
    echo "エラー: 現在のGitブランチを確認できません。"
    exit 1
fi

echo
echo "=== ① 現在のブランチ ==="
echo "$BRANCH"

echo
echo "=== ② 変更ファイル ==="
if git status --short | grep -q .; then
    git status --short
else
    echo "保存する変更がありません。"
    exit 0
fi

# テストで自動更新される生成ファイルが、
# 実行前に未変更だったかを記録する
DECISION_REPORT="results/decision_log_report.csv"
RESTORE_DECISION_REPORT=false

if git diff --quiet -- "$DECISION_REPORT" &&
   git diff --cached --quiet -- "$DECISION_REPORT"; then
    RESTORE_DECISION_REPORT=true
fi

echo
echo "=== ③ 全テスト ==="
"$PYTHON" -m pytest -q

# 実行前に未変更だった生成ファイルだけ元へ戻す
if [ "$RESTORE_DECISION_REPORT" = true ]; then
    git restore --worktree -- "$DECISION_REPORT" 2>/dev/null || true
fi

echo
echo "✅ 全テストに合格しました。"

echo
echo "=== ④ 変更内容の要約 ==="
git diff --stat
git diff --cached --stat || true

echo
read -r -p "コミットメッセージを入力してください: " COMMIT_MESSAGE

if [ -z "${COMMIT_MESSAGE// }" ]; then
    echo "エラー: コミットメッセージが空です。"
    exit 1
fi

echo
echo "=== ⑤ Gitへ追加 ==="
git add -A

echo
echo "=== ⑥ コミット ==="
git commit -m "$COMMIT_MESSAGE"

echo
echo "=== ⑦ GitHubへプッシュ ==="
if git rev-parse --abbrev-ref --symbolic-full-name '@{upstream}' >/dev/null 2>&1; then
    git push
else
    git push --set-upstream origin "$BRANCH"
fi

echo
echo "========================================"
echo "✅ テスト・コミット・プッシュが完了しました。"
echo "ブランチ: $BRANCH"
echo "========================================"

#!/usr/bin/env bash
set -euo pipefail

echo "=== AI自動売買システム 開発チェック ==="
echo "現在のブランチ: $(git branch --show-current)"

echo
echo "[1/3] Python構文チェック"
find . -maxdepth 1 -type f -name "*.py" -print0 |
    xargs -0 -r python -m py_compile
echo "OK: Python構文エラーなし"

echo
echo "[2/3] Git差分チェック"
git diff --check
echo "OK: 不正な空白や差分エラーなし"

echo
echo "[3/3] Git状態"
git status --short

echo
echo "=== すべてのチェックが完了しました ==="

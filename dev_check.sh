#!/usr/bin/env bash

set -u

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
PYTHON="$PROJECT_DIR/.venv/bin/python"

cd "$PROJECT_DIR" || exit 1

echo
echo "========================================"
echo " AI Asset Platform 自動確認"
echo "========================================"

if [ ! -x "$PYTHON" ]; then
    echo "エラー: 仮想環境のPythonが見つかりません。"
    echo "確認場所: $PYTHON"
    exit 1
fi

echo
echo "=== ① 現在のブランチ ==="
git branch --show-current

echo
echo "=== ② 変更ファイル ==="
if git status --short | grep -q .; then
    git status --short
else
    echo "変更ファイルはありません。"
fi

echo
echo "=== ③ 全テスト ==="
if "$PYTHON" -m pytest -q; then
    echo
    echo "✅ 全テストに合格しました。"
else
    echo
    echo "❌ テストに失敗しました。"
    echo "Gitへの保存は行わず、修正が必要です。"
    exit 1
fi

echo
echo "=== ④ 変更内容の要約 ==="
if git diff --stat | grep -q .; then
    git diff --stat
else
    echo "未コミットの差分はありません。"
fi

echo
echo "=== ⑤ Git状態 ==="
git status --short

echo
echo "========================================"
echo "✅ 自動確認が正常に完了しました。"
echo "========================================"

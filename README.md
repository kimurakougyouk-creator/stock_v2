# stock_v2

日本株のバックテスト設定を探索し、レポートを生成するためのPythonプロジェクトです。

## 初回セットアップ

1. リポジトリを取得します。
2. 次のコマンドを実行します。

```bash
bash scripts/setup.sh
```

このコマンドは `.venv` を作成し、`requirements.txt` の依存関係をインストールし、`results/` と `.env` を用意します。

## メール設定

メール送信を使う場合は、`.env` または環境変数で次のキーを設定してください。
値はログに表示されません。

```bash
EMAIL_ADDRESS=
APP_PASSWORD=
```

秘密情報をリポジトリへコミットしないでください。`.env` と `.env.*` はGit管理対象外です。

## テスト・チェック

```bash
bash scripts/check.sh
```

このコマンドは次を実行します。

- Pythonファイルの構文チェック
- pytest
- 主要モジュールのimport確認
- `EMAIL_ADDRESS` と `APP_PASSWORD` の設定有無確認（値は表示しません）

## 実行

```bash
bash scripts/run.sh
```

このコマンドは `.venv` を有効化し、事前チェック後に `main_simple_step8.py` を実行します。
メール設定が未設定の場合は、値を表示せずに分かりやすいエラーを出して停止します。

## 生成ファイル

バックテスト実行で作成されるExcel、PNG、`results/` 配下のファイルはGit管理対象外です。
実行後に生成ファイルが増えても、通常は `git status` に表示されません。

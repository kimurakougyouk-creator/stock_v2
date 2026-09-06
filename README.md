# stock_v2

## 初回セットアップ

Chromebookなどの新しい環境では、リポジトリ直下で次の1コマンドを実行してください。

```bash
bash scripts/setup.sh
```

このコマンドは `.venv` の作成、依存関係のインストール、既存テストの実行までをまとめて行います。

## 通常起動

```bash
bash scripts/run.sh
```

`scripts/run.sh` は正式な `start.sh` を呼び出します。実際の秘密情報は `.env` にのみ保存し、Gitには追加しないでください。必要な項目名だけを `.env.example` で確認できます。

## Paper共通基盤の最終監査

TWS / IBKR Gateway の Paper Trading にログインした状態で、次の1コマンドを実行します。

```bash
bash scripts/audit_paper_foundation.sh
```

この監査は、Git管理ファイルの秘密情報スキャン、全pytest、IBKR Paperのno-transmit smoke testを順番に実行します。Live Tradingを有効化せず、注文送信もしません。

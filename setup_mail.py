from __future__ import annotations

import getpass
import os
from pathlib import Path


def _escape_env_value(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def main() -> None:
    print("====================================")
    print(" 自動売買システム・メール初回設定")
    print("====================================")
    print()

    email = input("Gmailアドレスを入力してください: ").strip()
    password = getpass.getpass("Googleのアプリパスワードを入力してください（画面には表示されません）: ").strip()

    if "@" not in email:
        print("入力されたメールアドレスを確認してください。")
        raise SystemExit(1)
    if not password:
        print("アプリパスワードが入力されていません。")
        raise SystemExit(1)

    env_path = Path(__file__).resolve().parent / ".env"
    env_path.write_text(
        f'export EMAIL_ADDRESS="{_escape_env_value(email)}"\n'
        f'export APP_PASSWORD="{_escape_env_value(password)}"\n',
        encoding="utf-8",
    )
    os.chmod(env_path, 0o600)

    print()
    print("メール設定を安全に保存しました。")
    print("今後は start.sh を実行するだけで設定が読み込まれます。")


if __name__ == "__main__":
    main()

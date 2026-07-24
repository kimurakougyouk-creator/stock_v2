from getpass import getpass
from pathlib import Path

ENV_FILE = Path(".env")


def shell_quote(value: str) -> str:
    return "'" + value.replace("'", "'\\''") + "'"


def write_env_file(email_address: str, app_password: str, env_file: Path = ENV_FILE) -> None:
    env_file.write_text(
        "\n".join([
            f"EMAIL_ADDRESS={shell_quote(email_address)}",
            f"APP_PASSWORD={shell_quote(app_password)}",
            "",
        ]),
        encoding="utf-8",
    )


def has_mail_settings(env_file: Path = ENV_FILE) -> bool:
    if not env_file.exists():
        return False

    text = env_file.read_text(encoding="utf-8")
    return "EMAIL_ADDRESS=" in text and "APP_PASSWORD=" in text


def run_wizard(env_file: Path = ENV_FILE, input_func=input, password_func=getpass) -> bool:
    print("初回設定を開始します。Gmail通知に使う情報を入力してください。")
    print("入力内容はこのPCの .env にだけ保存され、GitHubには保存されません。")

    email_address = input_func("Gmailアドレス: ").strip()
    app_password = password_func("Gmailアプリパスワード（画面には表示されません）: ").strip()

    if not email_address or not app_password:
        print("メール設定が入力されていません。もう一度 bash start.sh を実行してください。")
        return False

    write_env_file(email_address, app_password, env_file)
    print("設定を .env に保存しました。")
    return True


if __name__ == "__main__":
    import sys

    if "--check" in sys.argv:
        raise SystemExit(0 if has_mail_settings() else 1)

    raise SystemExit(0 if run_wizard() else 1)

from getpass import getpass
from pathlib import Path

ENV_FILE = Path(".env")


def shell_quote(value: str) -> str:
    """環境変数値を .env で安全に読める形へクォートする。"""
    return "'" + value.replace("'", "'\\''") + "'"


def write_env_file(email_address: str, app_password: str, env_file: Path = ENV_FILE) -> None:
    """初回設定内容をローカル専用 .env に保存する。"""
    content = "\n".join([
        f"EMAIL_ADDRESS={shell_quote(email_address)}",
        f"APP_PASSWORD={shell_quote(app_password)}",
        "BROKER_MODE=dry_run",
        "DRY_RUN_ORDER_FILE=results/dry_run_orders.json",
        "LOG_DIR=results",
        "",
    ])
    env_file.write_text(content, encoding="utf-8")


def has_required_mail_settings(env_file: Path = ENV_FILE) -> bool:
    """メール通知に必要な設定が .env に存在するか確認する。"""
    if not env_file.exists():
        return False

    values = _read_env_values(env_file)
    return bool(values.get("EMAIL_ADDRESS") and values.get("APP_PASSWORD"))


def run_wizard(env_file: Path = ENV_FILE, input_func=input, password_func=getpass) -> bool:
    """初心者向けの初回メール設定ウィザードを実行する。"""
    print("初回設定を開始します。Gmail通知に使う情報を入力してください。")
    print("入力内容はGitHubには保存されず、このChromebook内の .env にだけ保存されます。")

    email_address = input_func("Gmailアドレス: ").strip()
    app_password = password_func("Gmailアプリパスワード（画面には表示されません）: ").strip()

    if not email_address or not app_password:
        print("メール設定が未入力のため保存できませんでした。")
        return False

    write_env_file(email_address, app_password, env_file)
    print(f"設定を保存しました: {env_file}")
    return True


def _read_env_values(env_file: Path) -> dict[str, str]:
    values = {}
    for line in env_file.read_text(encoding="utf-8").splitlines():
        if not line or line.lstrip().startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip("'\"")
    return values


if __name__ == "__main__":
    import sys

    if "--check" in sys.argv:
        raise SystemExit(0 if has_required_mail_settings() else 1)

    raise SystemExit(0 if run_wizard() else 1)

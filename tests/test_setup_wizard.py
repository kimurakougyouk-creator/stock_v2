from setup_wizard import has_mail_settings, run_wizard, shell_quote, write_env_file


def test_shell_quote_escapes_single_quote():
    assert shell_quote("ab'cd") == "'ab'\\''cd'"


def test_write_env_file_saves_local_env(tmp_path):
    env_file = tmp_path / ".env"

    write_env_file("user@example.com", "app-password", env_file)

    content = env_file.read_text(encoding="utf-8")
    assert "EMAIL_ADDRESS='user@example.com'" in content
    assert "APP_PASSWORD='app-password'" in content
    assert has_mail_settings(env_file)


def test_run_wizard_rejects_blank_values(tmp_path):
    env_file = tmp_path / ".env"

    result = run_wizard(
        env_file,
        input_func=lambda _prompt: "",
        password_func=lambda _prompt: "",
    )

    assert not result
    assert not env_file.exists()

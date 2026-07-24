import importlib
import os
import runpy

import pytest


def test_config_reads_app_password_from_environment(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "dummy-secret-from-env")

    namespace = runpy.run_path("config.py")

    assert namespace["APP_PASSWORD"] == "dummy-secret-from-env"


def test_config_auto_loads_env_file_from_repo_root(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("EMAIL_ADDRESS='dotenv@example.com'\nAPP_PASSWORD='dotenv-secret'\n", encoding="utf-8")

    import config

    reloaded = importlib.reload(config)

    assert reloaded.EMAIL_ADDRESS == "dotenv@example.com"
    assert reloaded.APP_PASSWORD == "dotenv-secret"


def test_send_mail_requires_app_password():
    from mail import send_mail

    with pytest.raises(ValueError, match="APP_PASSWORD"):
        send_mail("sender@example.com", "", "receiver@example.com", "subject", "body")

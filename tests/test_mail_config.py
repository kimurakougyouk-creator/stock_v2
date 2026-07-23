import os
import runpy

import pytest


def test_config_reads_app_password_from_environment(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "dummy-secret-from-env")

    namespace = runpy.run_path("config.py")

    assert namespace["APP_PASSWORD"] == "dummy-secret-from-env"


def test_send_mail_requires_app_password():
    from mail import send_mail

    with pytest.raises(ValueError, match="APP_PASSWORD"):
        send_mail("sender@example.com", "", "receiver@example.com", "subject", "body")

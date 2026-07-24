import smtplib

from mail import send_mail


def test_send_mail_skips_when_credentials_are_missing():
    assert not send_mail("sender@example.com", "", "receiver@example.com", "subject", "body")


def test_send_mail_returns_false_on_smtp_error(monkeypatch):
    class BrokenSMTP:
        def __init__(self, *args, **kwargs):
            raise smtplib.SMTPException("smtp unavailable")

    monkeypatch.setattr(smtplib, "SMTP", BrokenSMTP)

    assert not send_mail("sender@example.com", "password", "receiver@example.com", "subject", "body")

"""Regression tests for Issue #285 Stage 2, mail slice: moving `send_mail`'s
implementation from the root-level `mail.py` into
`ai_asset_platform.notifications.mail`, with `mail.py` kept as a
backward-compatibility shim and `signal_runner.py` (and the Paper
operations monitor's lazy fallback import) updated to import the package
implementation directly.

`mail.py` uses a `sys.modules` aliasing shim (the same technique as
`decision_logger.py`) rather than a plain `from ... import` re-export:
`send_mail` references `smtplib`/`MIMEText` as unqualified module globals
inside its function body, not as parameters, so a plain re-export would
create separate bindings on the shim that `send_mail` never reads --
silently making any `monkeypatch.setattr(mail, "smtplib", ...)` pattern
ineffective. Aliasing `sys.modules["mail"]` to the package module object
keeps both names sharing one namespace.

No real SMTP connection is made anywhere in this file.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]


class _FakeSMTP:
    """In-memory stand-in for smtplib.SMTP. Never touches the network."""

    instances: list["_FakeSMTP"] = []

    def __init__(self, host, port):
        self.host = host
        self.port = port
        self.started_tls = False
        self.login_args = None
        self.sent_message = None
        _FakeSMTP.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def starttls(self):
        self.started_tls = True

    def login(self, sender, app_password):
        self.login_args = (sender, app_password)

    def send_message(self, msg):
        self.sent_message = msg


def test_send_mail_importable_from_package():
    """The implementation lives in the package now."""
    from ai_asset_platform.notifications.mail import send_mail

    assert callable(send_mail)


def test_root_mail_is_the_same_module_as_the_package():
    """`mail` (root) and `ai_asset_platform.notifications.mail` (package)
    must be the *same* module object -- not two separate namespaces that
    could drift out of sync -- so monkeypatching one is visible through
    the other.
    """
    import mail
    import ai_asset_platform.notifications.mail as package_mail

    assert mail is package_mail
    assert mail.send_mail is package_mail.send_mail


def test_root_mail_has_no_duplicated_implementation():
    """The root shim must not re-implement send_mail -- it must delegate
    to the package entirely.
    """
    text = (ROOT_DIR / "mail.py").read_text(encoding="utf-8")

    assert "def send_mail" not in text
    assert "ai_asset_platform.notifications" in text


def test_signal_runner_does_not_import_from_root_mail():
    """Static regression: `signal_runner.py` must import the package
    implementation directly (`ai_asset_platform.notifications.mail`), not
    the root-level compatibility shim (`from mail import ...`).
    """
    signal_runner_path = ROOT_DIR / "signal_runner.py"
    text = signal_runner_path.read_text(encoding="utf-8")

    assert "from mail import" not in text, (
        "signal_runner.py must not import from the root mail shim"
    )
    assert "from ai_asset_platform.notifications.mail import" in text, (
        "signal_runner.py must import send_mail from the package "
        "implementation directly"
    )


def test_paper_operations_monitor_lazy_fallback_uses_package_import():
    """Static regression: the Paper operations monitor's lazy fallback
    import (used only when no send_mail_fn is injected) must import the
    package implementation directly, not the root shim.
    """
    monitor_path = (
        ROOT_DIR
        / "src"
        / "ai_asset_platform"
        / "brokers"
        / "ibkr_paper_operations_monitor.py"
    )
    text = monitor_path.read_text(encoding="utf-8")

    assert "from mail import" not in text, (
        "ibkr_paper_operations_monitor.py must not import from the root "
        "mail shim"
    )
    assert "from ai_asset_platform.notifications.mail import" in text


def test_package_import_does_not_require_repo_root_on_sys_path(tmp_path):
    """Isolated regression, offline (no network, no venv creation, no
    dependency reinstall): import `ai_asset_platform.notifications.mail`
    in a subprocess whose cwd is *not* the repo root and whose PYTHONPATH
    is set to `src/` only -- never the repo root itself, so root-level
    modules like `mail.py` or `signal_runner.py` are never on the import
    path at all. This proves resolution *correctness* (it resolves to
    this checkout's own package file, not the root-level shim, regardless
    of cwd), not resolution *mechanism*.

    Deliberately does NOT assert that removing PYTHONPATH breaks the
    import: in CI, `pip install -e .` already ran before this test suite,
    so `ai_asset_platform` resolves via the editable install regardless of
    PYTHONPATH -- asserting the opposite would be an environment-dependent
    false failure there, not a real regression in this checkout.

    Also confirms that merely importing the module never opens a network
    connection (no smtplib.SMTP call happens at import time).
    """
    src_dir = ROOT_DIR / "src"
    expected_module_path = (
        src_dir / "ai_asset_platform" / "notifications" / "mail.py"
    ).resolve()
    assert expected_module_path.is_file()

    env = dict(os.environ)
    # Only ever add src/ -- never the repo root -- so root-level modules
    # stay unreachable regardless of what else this interpreter already
    # has installed (e.g. an unrelated checkout's editable install, if
    # this test happens to run under a borrowed/shared venv).
    env["PYTHONPATH"] = str(src_dir)

    script = (
        "import ai_asset_platform.notifications.mail as m\n"
        "import sys\n"
        "assert 'mail' not in sys.modules, ("
        "'root-level mail must not have been imported')\n"
        "print(m.__file__)\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=str(tmp_path),
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, (
        f"isolated package import failed:\nstdout={result.stdout}\nstderr={result.stderr}"
    )

    resolved_module_path = Path(result.stdout.strip()).resolve()
    assert resolved_module_path == expected_module_path, (
        "ai_asset_platform.notifications.mail resolved to a different "
        f"file than this checkout's own module: {resolved_module_path} "
        f"(expected {expected_module_path})"
    )


def test_monkeypatched_root_smtplib_is_honored_by_send_mail(monkeypatch):
    """The root shim aliasing must keep monkeypatch-on-root fully
    effective: patching `mail.smtplib.SMTP` (root import) must be what
    `send_mail` actually uses, proving the sys.modules aliasing shim
    works exactly like it does for decision_logger.py. No real network
    connection is made -- _FakeSMTP is purely in-memory.
    """
    import mail

    _FakeSMTP.instances = []
    monkeypatch.setattr(mail.smtplib, "SMTP", _FakeSMTP)

    mail.send_mail(
        "sender@example.com",
        "app-password",
        "receiver@example.com",
        "subject",
        "body",
    )

    assert len(_FakeSMTP.instances) == 1
    fake = _FakeSMTP.instances[0]
    assert fake.host == "smtp.gmail.com"
    assert fake.port == 587
    assert fake.started_tls is True
    assert fake.login_args == ("sender@example.com", "app-password")
    assert fake.sent_message is not None
    assert fake.sent_message["Subject"] == "subject"


def test_send_mail_never_touches_real_network_when_fake_smtp_raises_on_real_use(
    monkeypatch,
):
    """Extra safety net: install a fake smtplib.SMTP that raises
    immediately if instantiated with anything resembling a real
    connection attempt signature mismatch, confirming send_mail's call
    shape only ever goes through the injected fake.
    """
    import mail

    class _RaisingIfMisused:
        def __init__(self, host, port):
            if host != "smtp.gmail.com" or port != 587:
                raise AssertionError(
                    "unexpected SMTP target -- possible real network attempt"
                )
            self.started_tls = False
            self.login_args = None
            self.sent_message = None

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def starttls(self):
            self.started_tls = True

        def login(self, sender, app_password):
            self.login_args = (sender, app_password)

        def send_message(self, msg):
            self.sent_message = msg

    monkeypatch.setattr(mail.smtplib, "SMTP", _RaisingIfMisused)

    mail.send_mail(
        "sender@example.com",
        "app-password",
        "receiver@example.com",
        "subject",
        "body",
    )

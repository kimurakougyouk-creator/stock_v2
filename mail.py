"""Backward-compatibility shim for the root-level ``mail`` import path.

The real implementation (``send_mail``) now lives in
``ai_asset_platform.notifications.mail``. ``send_mail`` references
``smtplib``/``MIMEText`` as unqualified module globals rather than
parameters, so a plain ``from ... import send_mail`` re-export would leave
any test/caller that monkeypatches ``mail.smtplib`` (or similar root
attributes) unable to affect what ``send_mail`` actually uses -- it would
silently keep using the package module's own ``smtplib`` binding.

Instead, this module replaces its own entry in ``sys.modules`` with the
package module object (the same technique used by ``decision_logger.py`` in
this Stage 2 series), so ``import mail`` resolves to the exact same module
(same namespace) as ``ai_asset_platform.notifications.mail``. This keeps
every existing attribute-level interaction -- reads, writes, and any
``monkeypatch.setattr(mail, "smtplib", fake_smtplib)`` -- fully transparent
and behavior-preserving.
"""

import sys

from ai_asset_platform.notifications import mail as _mail

sys.modules[__name__] = _mail

"""Backward-compatibility shim for the root-level ``decision_logger`` import
path.

The real implementation (``LOG_FILE``, ``FIELDNAMES``, ``log_decision``,
etc.) now lives in ``ai_asset_platform.reports.decision_logger``.
``log_decision`` and ``_upgrade_existing_log`` reference ``LOG_FILE`` as an
unqualified module global rather than a function parameter, so a plain
``from ... import log_decision, LOG_FILE`` re-export would create a
*separate* ``LOG_FILE`` binding here that ``log_decision`` itself never
reads -- callers (and tests) that monkeypatch ``decision_logger.LOG_FILE``
to redirect writes would silently stop working and fall through to the
real ``results/decision_log.csv`` path.

Instead, this module replaces its own entry in ``sys.modules`` with the
package module object, so ``import decision_logger`` resolves to the exact
same module (same namespace) as ``ai_asset_platform.reports.decision_logger``.
This keeps every existing attribute-level interaction -- reads, writes, and
``monkeypatch.setattr(decision_logger, "LOG_FILE", ...)`` -- fully
transparent and behavior-preserving.
"""

import sys

from ai_asset_platform.reports import decision_logger as _decision_logger

sys.modules[__name__] = _decision_logger

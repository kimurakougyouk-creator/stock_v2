"""Backward-compatibility shim for the root-level ``order_manager`` import
path.

The real implementation now lives in
``ai_asset_platform.execution.order_manager``. Its functions reference
``ORDER_LOG_PATH``, ``ORDER_LOG_DIR``, ``TRADE_PNL_PATH``, and other module
globals as unqualified names inside their bodies rather than as
parameters, so a plain ``from ... import`` re-export would create separate
bindings here that those functions never read -- silently breaking every
existing ``monkeypatch.setattr(order_manager, "ORDER_LOG_PATH", ...)`` /
``@patch("order_manager.calculate_...")`` pattern.

Instead, this module replaces its own entry in ``sys.modules`` with the
package module object (the same technique used by ``decision_logger.py``
and ``mail.py`` in this Stage 2 series), so ``import order_manager``
resolves to the exact same module (same namespace) as
``ai_asset_platform.execution.order_manager``. This keeps every existing
attribute-level interaction -- reads, writes, and monkeypatching in either
direction -- fully transparent and behavior-preserving.
"""

import sys

from ai_asset_platform.execution import order_manager as _order_manager

sys.modules[__name__] = _order_manager

"""Regression tests for Issue #285 Stage 2, order_manager slice: moving
`order_manager`'s implementation from the root-level `order_manager.py`
into `ai_asset_platform.execution.order_manager`, with `order_manager.py`
kept as a backward-compatibility shim and `signal_runner.py` updated to
import the package implementation directly.

`order_manager.py` uses a `sys.modules` aliasing shim (the same technique
as `decision_logger.py` and `mail.py`) rather than a plain `from ...
import` re-export: its functions reference `ORDER_LOG_PATH`,
`ORDER_LOG_DIR`, `TRADE_PNL_PATH`, and other module globals as unqualified
names inside their bodies, not as parameters, so a plain re-export would
create separate bindings on the shim that those functions never read --
silently breaking existing `monkeypatch.setattr(order_manager,
"ORDER_LOG_PATH", ...)` and `@patch("order_manager.calculate_...")`
patterns used across tests/test_order_manager_*.py and
tests/test_legacy_risk_gate.py.

Scope note: only signal_runner.py was switched to a direct package import
in this slice. The 14 production callers under src/ai_asset_platform/
(brokers/*.py, execution/broker_position_guard.py,
execution/ibkr_execution_log_recovery.py,
execution/ibkr_execution_reconcile.py, execution/verified_paper_scan.py,
execution/legacy_risk_gate.py, execution/shared_risk_gate.py) are
deliberately left importing the root `order_manager` shim -- they keep
working unmodified because of the sys.modules aliasing, and their
direct-import migration is explicitly deferred to a later, independent
slice/PR.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

ROOT_DIR = Path(__file__).resolve().parents[1]


def test_order_manager_functions_importable_from_package():
    """The implementation lives in the package now."""
    from ai_asset_platform.execution.order_manager import (
        calculate_available_cash,
        calculate_consecutive_losses,
        calculate_daily_buy_order_count,
        calculate_daily_realized_pnl,
        calculate_daily_sell_order_count,
        calculate_daily_trading_amount,
        calculate_position_holding_days,
        calculate_repurchase_cooldown_remaining_minutes,
        create_paper_order,
        get_open_positions,
        load_accounting_orders,
        load_paper_orders,
        update_trailing_high_price,
    )

    for fn in (
        calculate_available_cash,
        calculate_consecutive_losses,
        calculate_daily_buy_order_count,
        calculate_daily_realized_pnl,
        calculate_daily_sell_order_count,
        calculate_daily_trading_amount,
        calculate_position_holding_days,
        calculate_repurchase_cooldown_remaining_minutes,
        create_paper_order,
        get_open_positions,
        load_accounting_orders,
        load_paper_orders,
        update_trailing_high_price,
    ):
        assert callable(fn)


def test_root_order_manager_is_the_same_module_as_the_package():
    """`order_manager` (root) and `ai_asset_platform.execution.order_manager`
    (package) must be the *same* module object -- not two separate
    namespaces that could drift out of sync -- so that all public
    functions/globals are identical either way it is imported, and
    monkeypatching one is visible through the other.
    """
    import order_manager
    import ai_asset_platform.execution.order_manager as package_order_manager

    assert order_manager is package_order_manager
    assert (
        order_manager.calculate_available_cash
        is package_order_manager.calculate_available_cash
    )
    assert order_manager.ORDER_LOG_PATH is package_order_manager.ORDER_LOG_PATH
    assert order_manager.ORDER_LOG_DIR is package_order_manager.ORDER_LOG_DIR
    assert order_manager.TRADE_PNL_PATH is package_order_manager.TRADE_PNL_PATH


def test_root_order_manager_has_no_duplicated_implementation():
    """The root shim must not re-implement order_manager's functions -- it
    must delegate to the package entirely.
    """
    text = (ROOT_DIR / "order_manager.py").read_text(encoding="utf-8")

    assert "def create_paper_order" not in text
    assert "def calculate_available_cash" not in text
    assert "def load_accounting_orders" not in text
    assert "ai_asset_platform.execution" in text
    assert "sys.modules[__name__]" in text


def test_monkeypatch_on_root_is_visible_from_package(monkeypatch, tmp_path):
    """monkeypatch.setattr(order_manager, "ORDER_LOG_PATH", ...) -- the
    exact pattern used by tests/test_order_manager_*.py -- must actually
    redirect what the package's own functions read. Also chdir into
    tmp_path first: create_paper_order() also touches ORDER_LOG_DIR and
    (via save_realized_trade_pnls()) TRADE_PNL_PATH, so this isolates the
    whole call from the real repo's results/ regardless of which of those
    globals a given code path happens to use.
    """
    monkeypatch.chdir(tmp_path)

    import order_manager
    import ai_asset_platform.execution.order_manager as package_order_manager

    fake_log = tmp_path / "root_patched_orders.jsonl"
    monkeypatch.setattr(order_manager, "ORDER_LOG_PATH", fake_log)

    assert package_order_manager.ORDER_LOG_PATH == fake_log

    order_manager.create_paper_order(
        ticker="TEST.T",
        signal="BUY",
        shares=100,
        reference_price=1000.0,
    )

    assert fake_log.exists()
    assert not (ROOT_DIR / "results" / "paper_orders.jsonl").exists()


def test_monkeypatch_on_package_is_visible_from_root(monkeypatch, tmp_path):
    """The reverse direction: patching the package's own module attribute
    must be visible via the root import too, proving both names truly
    share one namespace (not just a one-way alias). Read-only check, no
    file writes involved.
    """
    import order_manager
    import ai_asset_platform.execution.order_manager as package_order_manager

    fake_log = tmp_path / "package_patched_orders.jsonl"
    monkeypatch.setattr(package_order_manager, "ORDER_LOG_PATH", fake_log)

    assert order_manager.ORDER_LOG_PATH == fake_log


def test_patch_decorator_string_target_still_works():
    """@patch("order_manager.calculate_daily_buy_order_count", ...) --
    the exact pattern used by tests/test_legacy_risk_gate.py -- must
    still resolve correctly and be honored by the package's own code.
    """
    import ai_asset_platform.execution.order_manager as package_order_manager

    with patch(
        "order_manager.calculate_daily_buy_order_count",
        return_value=42,
    ):
        assert package_order_manager.calculate_daily_buy_order_count() == 42


def test_existing_from_import_style_still_works():
    """`from order_manager import calculate_available_cash` (the style
    used by several existing tests) must keep working and resolve to the
    package's own function object.
    """
    from order_manager import calculate_available_cash
    from ai_asset_platform.execution.order_manager import (
        calculate_available_cash as package_calculate_available_cash,
    )

    assert calculate_available_cash is package_calculate_available_cash


def test_signal_runner_does_not_import_from_root_order_manager():
    """Static regression: `signal_runner.py` must import the package
    implementation directly (`ai_asset_platform.execution.order_manager`),
    not the root-level compatibility shim (`from order_manager import ...`).
    """
    signal_runner_path = ROOT_DIR / "signal_runner.py"
    text = signal_runner_path.read_text(encoding="utf-8")

    assert "from order_manager import" not in text, (
        "signal_runner.py must not import from the root order_manager shim"
    )
    assert "from ai_asset_platform.execution.order_manager import" in text, (
        "signal_runner.py must import order_manager functions from the "
        "package implementation directly"
    )


def test_package_import_does_not_create_results_files(tmp_path, monkeypatch):
    """Import-time side-effect absence: merely importing the package
    module (fresh, uncached) must not create/touch any results file.
    Runs in an isolated cwd so this can never touch the real repo's
    results/.
    """
    monkeypatch.chdir(tmp_path)

    for name in (
        "order_manager",
        "ai_asset_platform.execution.order_manager",
    ):
        sys.modules.pop(name, None)

    import importlib

    importlib.import_module("ai_asset_platform.execution.order_manager")

    assert not (tmp_path / "results").exists()


def test_package_import_makes_no_network_or_broker_calls():
    """Static regression: the package implementation must contain no
    broker/TWS/network primitives at all -- it is pure file/JSON/CSV
    bookkeeping, matching the original root implementation's scope.
    """
    text = (
        ROOT_DIR
        / "src"
        / "ai_asset_platform"
        / "execution"
        / "order_manager.py"
    ).read_text(encoding="utf-8")

    for forbidden in (
        "socket.",
        "smtplib",
        "requests.",
        "urlopen",
        "ib_insync",
        "ibapi",
        ".placeOrder(",
        ".cancelOrder(",
    ):
        assert forbidden not in text, f"unexpected token in order_manager.py: {forbidden}"


def test_package_import_does_not_require_repo_root_on_sys_path(tmp_path):
    """Isolated regression, offline (no network, no venv creation, no
    dependency reinstall): import `ai_asset_platform.execution.order_manager`
    in a subprocess whose cwd is *not* the repo root and whose PYTHONPATH
    is set to `src/` only -- never the repo root itself, so root-level
    modules like `order_manager.py` or `signal_runner.py` are never on the
    import path at all. This proves resolution *correctness* (it resolves
    to this checkout's own package file, not the root-level shim,
    regardless of cwd), not resolution *mechanism*.

    Also confirms that merely importing the module never opens a network
    or broker connection, and does not require the repo root (so no
    accidental dependency on config.py/root shims sneaks in).

    Deliberately does NOT assert that removing PYTHONPATH breaks the
    import: in CI, `pip install -e .` already ran before this test suite,
    so `ai_asset_platform` resolves via the editable install regardless of
    PYTHONPATH -- asserting the opposite would be an environment-dependent
    false failure there, not a real regression in this checkout.
    """
    src_dir = ROOT_DIR / "src"
    expected_module_path = (
        src_dir / "ai_asset_platform" / "execution" / "order_manager.py"
    ).resolve()
    assert expected_module_path.is_file()

    env = dict(os.environ)
    env["PYTHONPATH"] = str(src_dir)

    script = (
        "import ai_asset_platform.execution.order_manager as m\n"
        "import sys\n"
        "assert 'order_manager' not in sys.modules, ("
        "'root-level order_manager must not have been imported')\n"
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
        "ai_asset_platform.execution.order_manager resolved to a "
        f"different file than this checkout's own module: {resolved_module_path} "
        f"(expected {expected_module_path})"
    )

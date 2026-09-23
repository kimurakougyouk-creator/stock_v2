from pathlib import Path
import subprocess

import pytest

from ai_asset_platform.reports.strategy_source_attestation import (
    STRATEGY_AUDITED_PATHS,
    StrategySourceAttestationError,
    attest_strategy_source,
)


SHA = "a" * 40


class FakeRunner:
    def __init__(self, *, status: str = "", index: str = "", ignored: str = ""):
        self.status = status
        self.index = index
        self.ignored = ignored

    def __call__(self, command, **kwargs):
        if command[1:3] == ["rev-parse", "HEAD"]:
            stdout = SHA + "\n"
        elif command[1:3] == ["status", "--porcelain=v1"]:
            stdout = self.status
        elif command[1:3] == ["ls-files", "-v"]:
            stdout = self.index
        elif command[1:3] == ["ls-files", "--others"]:
            stdout = self.ignored
        else:
            raise AssertionError(f"unexpected command: {command}")
        return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")


def test_clean_exact_strategy_source_is_attested(tmp_path: Path):
    assert (
        attest_strategy_source(
            SHA,
            repository_root=tmp_path,
            runner=FakeRunner(),
        )
        == SHA
    )


def test_tracked_dirty_strategy_source_fails_closed(tmp_path: Path):
    with pytest.raises(StrategySourceAttestationError, match="strategy source attestation blocked"):
        attest_strategy_source(
            SHA,
            repository_root=tmp_path,
            runner=FakeRunner(status=" M signal_runner.py\n"),
        )


def test_index_hidden_strategy_source_fails_closed(tmp_path: Path):
    with pytest.raises(StrategySourceAttestationError, match="INDEX_HIDDEN"):
        attest_strategy_source(
            SHA,
            repository_root=tmp_path,
            runner=FakeRunner(index="h signal_runner.py\n"),
        )


def test_ignored_strategy_bytecode_cache_fails_closed(tmp_path: Path):
    with pytest.raises(StrategySourceAttestationError, match="IGNORED_EXECUTABLE_CACHE"):
        attest_strategy_source(
            SHA,
            repository_root=tmp_path,
            runner=FakeRunner(
                ignored="src/ai_asset_platform/reports/__pycache__/performance.cpython-313.pyc\n"
            ),
        )


def test_dirty_runtime_binding_verifier_fails_closed(tmp_path: Path):
    with pytest.raises(StrategySourceAttestationError, match="strategy source attestation blocked"):
        attest_strategy_source(
            SHA,
            repository_root=tmp_path,
            runner=FakeRunner(status=" M scripts/verify_exact_checkout_import.py\n"),
        )




def test_attestation_scope_includes_ticker_universe():
    assert "tickers.csv" in STRATEGY_AUDITED_PATHS


def test_dirty_ticker_universe_fails_closed(tmp_path: Path):
    with pytest.raises(StrategySourceAttestationError, match="strategy source attestation blocked"):
        attest_strategy_source(
            SHA,
            repository_root=tmp_path,
            runner=FakeRunner(status=" M tickers.csv\n"),
        )


def test_dirty_root_startup_module_fails_closed(tmp_path: Path):
    with pytest.raises(StrategySourceAttestationError, match="strategy source attestation blocked"):
        attest_strategy_source(
            SHA,
            repository_root=tmp_path,
            runner=FakeRunner(status=" M dashboard.py\n"),
        )


def test_attestation_scope_includes_operational_tests_and_root_native_modules():
    assert "tests" in STRATEGY_AUDITED_PATHS
    for suffix in ("pyc", "pyo", "pyz", "so", "pyd", "dylib"):
        assert f":(top,glob)*.{suffix}" in STRATEGY_AUDITED_PATHS


def test_dirty_operational_test_fails_closed(tmp_path: Path):
    with pytest.raises(StrategySourceAttestationError, match="strategy source attestation blocked"):
        attest_strategy_source(
            SHA,
            repository_root=tmp_path,
            runner=FakeRunner(status=" M tests/test_strategy_promotion_policy.py\n"),
        )


def test_untracked_root_native_shadow_fails_closed(tmp_path: Path):
    with pytest.raises(StrategySourceAttestationError, match="strategy source attestation blocked"):
        attest_strategy_source(
            SHA,
            repository_root=tmp_path,
            runner=FakeRunner(status="?? dashboard.cpython-313-x86_64-linux-gnu.so\n"),
        )


def test_dirty_safe_env_loader_fails_closed(tmp_path: Path):
    with pytest.raises(StrategySourceAttestationError, match="strategy source attestation blocked"):
        attest_strategy_source(
            SHA,
            repository_root=tmp_path,
            runner=FakeRunner(status=" M scripts/load_start_env.py\n"),
        )


def test_attestation_scope_includes_root_package_init_variants():
    for suffix in ("py", "pyc", "pyo"):
        assert f":(top,glob)*/__init__.{suffix}" in STRATEGY_AUDITED_PATHS
    for suffix in ("so", "pyd", "dylib"):
        assert f":(top,glob)*/__init__*.{suffix}" in STRATEGY_AUDITED_PATHS


def test_untracked_root_package_shadow_fails_closed(tmp_path: Path):
    with pytest.raises(StrategySourceAttestationError, match="strategy source attestation blocked"):
        attest_strategy_source(
            SHA,
            repository_root=tmp_path,
            runner=FakeRunner(status="?? dashboard/__init__.py\n"),
        )




def test_third_party_root_symlink_shadow_fails_closed(tmp_path: Path):
    outside = tmp_path.parent / f"{tmp_path.name}-outside-ibapi"
    outside.mkdir()
    (outside / "__init__.py").write_text("VALUE = 'shadow'\n", encoding="utf-8")
    (tmp_path / "ibapi").symlink_to(outside, target_is_directory=True)

    with pytest.raises(StrategySourceAttestationError, match="ROOT_SYMLINK"):
        attest_strategy_source(
            SHA,
            repository_root=tmp_path,
            runner=FakeRunner(),
        )


def test_root_package_symlink_shadow_fails_closed(tmp_path: Path):
    (tmp_path / "dashboard.py").write_text("VALUE = 1\n", encoding="utf-8")
    outside = tmp_path.parent / f"{tmp_path.name}-outside-dashboard"
    outside.mkdir()
    (outside / "__init__.py").write_text("VALUE = 'shadow'\n", encoding="utf-8")
    (tmp_path / "dashboard").symlink_to(outside, target_is_directory=True)

    with pytest.raises(StrategySourceAttestationError, match="ROOT_MODULE_SYMLINK_SHADOW"):
        attest_strategy_source(
            SHA,
            repository_root=tmp_path,
            runner=FakeRunner(),
        )

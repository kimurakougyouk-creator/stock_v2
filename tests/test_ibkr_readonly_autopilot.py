from pathlib import Path
import os
import shutil
import subprocess


STRICT_MONITOR_MODULE = (
    "ai_asset_platform.brokers.ibkr_paper_operations_monitor_strict"
)
PLAIN_STRICT_MONITOR = f"python -m {STRICT_MONITOR_MODULE}"


def test_readonly_autopilot_has_valid_bash_syntax():
    result = subprocess.run(
        ["bash", "-n", "ibkr_readonly_autopilot.sh"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_readonly_autopilot_installer_has_valid_bash_syntax():
    result = subprocess.run(
        ["bash", "-n", "install_ibkr_readonly_autopilot.sh"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_readonly_autopilot_only_invokes_strict_readonly_monitor():
    script = Path("ibkr_readonly_autopilot.sh").read_text(encoding="utf-8")
    assert STRICT_MONITOR_MODULE in script
    assert PLAIN_STRICT_MONITOR not in script
    assert "bash ./ibkr_auto.sh" not in script
    assert "ibkr_operator_checkpoint" not in script
    assert "ibkr_overnight_whatif" not in script
    assert "placeOrder(" not in script
    assert "ibkr_auto_close_cycle_once.sh" not in script
    assert "ibkr_overnight_e2e_once.sh" not in script
    assert "YES_CLOSE_ONE_SPY_PAPER" not in script
    assert "AI_ASSET_ENABLE_IBKR_PAPER=true" not in script
    assert "AI_ASSET_ENABLE_LIVE_TRADING" not in script
    assert "AI_ASSET_LIVE_TRADING_UNLOCKED" not in script
    assert "enable_live_trading" not in script.lower()
    assert "RUN_VERIFIED_PAPER_ONLY" not in script
    assert "ibkr_verified_paper_runtime_once.sh" not in script
    assert 'echo "ORDER API REQUEST SENT: False"' in script


def test_readonly_autopilot_uses_existing_isolated_runner_and_pinned_ibapi():
    script = Path("ibkr_readonly_autopilot.sh").read_text(encoding="utf-8")

    assert "/usr/bin/python3 -I -S" in script
    assert "$REPO_DIR/scripts/run_isolated_venv_python.py" in script
    assert f"-m {STRICT_MONITOR_MODULE}" in script
    assert "AI_ASSET_PLATFORM_ROOT=\"$REPO_DIR\"" in script
    assert "AI_ASSET_REQUIRE_PINNED_IBAPI=1" in script

    # The daemon no longer executes mutable venv activation code or a plain
    # cwd-derived Python import path before the strict monitor.
    assert "source .venv/bin/activate" not in script
    assert "python scripts/verify_exact_checkout_import.py" not in script
    assert "\n        python -m " not in script


def test_readonly_autopilot_enters_minimal_environment_before_bash():
    script = Path("ibkr_readonly_autopilot.sh").read_text(encoding="utf-8")

    assert script.startswith("#!/bin/sh\n")
    assert "/usr/bin/env -i" in script
    assert "/bin/bash --noprofile --norc" in script
    assert "IBKR_AUTOPILOT_SANITIZED=1" in script
    assert "PATH=/usr/local/bin:/usr/bin:/bin" in script

    # These Python/shell startup controls are deliberately absent from the
    # whitelist created by env -i.
    for inherited_name in (
        "PYTHONPATH=",
        "PYTHONHOME=",
        "PYTHONSTARTUP=",
        "BASH_ENV=",
        "ENV=",
    ):
        assert inherited_name not in script


def test_readonly_autopilot_preserves_only_needed_monitor_policy_settings():
    script = Path("ibkr_readonly_autopilot.sh").read_text(encoding="utf-8")

    required = (
        'IBKR_PAPER_MONITOR_MAX_RUNTIME_AGE_HOURS="${IBKR_PAPER_MONITOR_MAX_RUNTIME_AGE_HOURS:-96}"',
        'IBKR_PAPER_MONITOR_MAX_HISTORY_BYTES="${IBKR_PAPER_MONITOR_MAX_HISTORY_BYTES:-10485760}"',
        'IBKR_PAPER_MONITOR_EMAIL_ALERTS="${IBKR_PAPER_MONITOR_EMAIL_ALERTS:-auto}"',
        'IBKR_PAPER_MONITOR_EMAIL_COOLDOWN_HOURS="${IBKR_PAPER_MONITOR_EMAIL_COOLDOWN_HOURS:-12}"',
    )
    for line in required:
        assert line in script


def test_direct_launch_blocks_hostile_bash_env_and_path_before_repo_checks(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    script = repo / "ibkr_readonly_autopilot.sh"
    shutil.copy2("ibkr_readonly_autopilot.sh", script)
    script.chmod(0o755)

    home = tmp_path / "home"
    home.mkdir()
    hostile_bin = tmp_path / "hostile-bin"
    hostile_bin.mkdir()

    bash_env_marker = tmp_path / "bash-env-ran"
    hostile_git_marker = tmp_path / "hostile-git-ran"
    bash_env = tmp_path / "hostile-bash-env.sh"
    bash_env.write_text(
        f"printf hostile > {bash_env_marker!s}\n",
        encoding="utf-8",
    )
    hostile_git = hostile_bin / "git"
    hostile_git.write_text(
        "#!/bin/sh\n"
        f"printf hostile > {hostile_git_marker!s}\n"
        "exit 0\n",
        encoding="utf-8",
    )
    hostile_git.chmod(0o755)

    env = dict(os.environ)
    env.update(
        {
            "HOME": str(home),
            "IBKR_REPO_DIR": str(repo),
            "BASH_ENV": str(bash_env),
            "ENV": str(bash_env),
            "PATH": str(hostile_bin),
            "PYTHONPATH": str(tmp_path / "hostile-python"),
            "PYTHONHOME": str(tmp_path / "hostile-python-home"),
        }
    )
    completed = subprocess.run(
        [str(script)],
        cwd=repo,
        env=env,
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
    )

    assert completed.returncode == 2
    assert "unattended monitor must start from a valid local main commit" in completed.stderr
    assert not bash_env_marker.exists()
    assert not hostile_git_marker.exists()


def test_readonly_autopilot_keeps_running_when_monitor_is_not_ready():
    script = Path("ibkr_readonly_autopilot.sh").read_text(encoding="utf-8")
    assert "PAPER OPERATIONS CRITICAL" in script
    assert "PAPER OPERATIONS WARNING" in script
    assert "sleep \"$INTERVAL_SECONDS\"" in script


def test_readonly_autopilot_never_updates_or_executes_remote_source_unattended():
    script = Path("ibkr_readonly_autopilot.sh").read_text(encoding="utf-8")
    assert "git pull" not in script
    assert "git fetch" not in script
    assert "git switch" not in script
    assert "git checkout" not in script
    assert "PINNED_HEAD" in script
    assert "AUTOPILOT SOURCE BLOCKED" in script


def test_readonly_autopilot_requires_main_and_exact_pinned_head_before_monitor():
    script = Path("ibkr_readonly_autopilot.sh").read_text(encoding="utf-8")
    branch_at = script.index('current_branch="$(git branch --show-current')
    head_at = script.index('current_head="$(git rev-parse HEAD')
    branch_block_at = script.index('if [[ "$current_branch" != "main" ]]')
    head_block_at = script.index('elif [[ "$current_head" != "$PINNED_HEAD" ]]')
    monitor_at = script.index(STRICT_MONITOR_MODULE)
    assert branch_at < branch_block_at < monitor_at
    assert head_at < head_block_at < monitor_at


def test_readonly_autopilot_blocks_tracked_source_changes_but_allows_runtime_outputs():
    script = Path("ibkr_readonly_autopilot.sh").read_text(encoding="utf-8")
    assert "tracked_source_is_clean" in script
    assert "git diff --quiet HEAD" in script
    assert "git diff --cached --quiet HEAD" in script
    assert "':(exclude)results/**'" in script
    assert "':(exclude)data/**'" in script


def test_readonly_autopilot_has_one_time_safe_migration_pin():
    script = Path("ibkr_readonly_autopilot.sh").read_text(encoding="utf-8")
    assert "IBKR_AUTOPILOT_PIN_FILE" in script
    assert "IBKR_AUTOPILOT_PINNED_HEAD" in script
    assert "AUTOPILOT MIGRATION PIN" in script
    assert 'chmod 600 "$pin_tmp"' in script
    assert 'mv -f "$pin_tmp" "$PIN_FILE"' in script


def test_readonly_autopilot_bounds_interval_and_log_growth():
    script = Path("ibkr_readonly_autopilot.sh").read_text(encoding="utf-8")
    assert 'INTERVAL_SECONDS="${IBKR_AUTOPILOT_INTERVAL_SECONDS:-300}"' in script
    assert "INTERVAL_SECONDS < 30 || INTERVAL_SECONDS > 86400" in script
    assert 'MAX_LOG_BYTES="${IBKR_AUTOPILOT_MAX_LOG_BYTES:-5242880}"' in script
    assert "MAX_LOG_BYTES < 1048576 || MAX_LOG_BYTES > 104857600" in script
    assert 'ROTATED_LOG_FILE="$LOG_FILE.1"' in script
    assert "rotate_autopilot_log_if_needed" in script
    assert 'mv -f "$LOG_FILE" "$ROTATED_LOG_FILE"' in script
    assert "rm -f" not in script


def test_installer_runs_only_readonly_autopilot_service():
    script = Path("install_ibkr_readonly_autopilot.sh").read_text(encoding="utf-8")
    assert "ibkr_readonly_autopilot.sh" in script
    assert "ibkr_auto_close_cycle_once.sh" not in script
    assert "YES_CLOSE_ONE_SPY_PAPER" not in script
    assert "UMask=0077" in script
    assert "IBKR_PAPER_MONITOR_MAX_RUNTIME_AGE_HOURS=96" in script
    assert "IBKR_PAPER_MONITOR_MAX_HISTORY_BYTES=10485760" in script
    assert "IBKR_PAPER_MONITOR_EMAIL_ALERTS=auto" in script
    assert "IBKR_PAPER_MONITOR_EMAIL_COOLDOWN_HOURS=12" in script
    assert "tests/test_ibkr_account_snapshot.py" in script
    assert "tests/test_ibkr_paper_operations_monitor.py" in script
    assert "tests/test_ibkr_paper_operations_monitor_strict.py" in script
    assert "IBKR_AUTOPILOT_PIN_FILE=" in script
    assert "IBKR_AUTOPILOT_PINNED_HEAD=" in script
    assert 'chmod 600 "$pin_tmp"' in script
    assert "ExecStart=/bin/sh $REPO_DIR/ibkr_readonly_autopilot.sh" in script
    assert "ExecStart=/usr/bin/env bash" not in script
    assert "systemctl --user enable ibkr-readonly-autopilot.service" in script
    assert "systemctl --user restart ibkr-readonly-autopilot.service" in script
    assert "systemctl --user enable --now ibkr-readonly-autopilot.service" not in script


def test_paper_operations_monitor_once_wrapper_is_readonly():
    script = Path("ibkr_paper_operations_monitor_once.sh").read_text(encoding="utf-8")
    assert PLAIN_STRICT_MONITOR in script
    assert "tests/test_ibkr_paper_operations_monitor_strict.py" in script
    assert "RUN_VERIFIED_PAPER_ONLY" not in script
    assert "AI_ASSET_ENABLE_IBKR_PAPER" not in script
    assert "ibkr_verified_paper_runtime_once.sh" not in script
    result = subprocess.run(
        ["bash", "-n", "ibkr_paper_operations_monitor_once.sh"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr

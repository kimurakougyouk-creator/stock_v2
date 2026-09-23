from pathlib import Path
import json
import os
import shutil
import subprocess
import sys


SCRIPT = Path(__file__).parents[1] / "scripts" / "verify_strategy_source_clean.sh"


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )


def _repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / "scripts").mkdir(parents=True)
    shutil.copy2(SCRIPT, root / "scripts" / SCRIPT.name)
    (root / "signal_runner.py").write_text("VALUE = 1\n", encoding="utf-8")
    _git(root, "init")
    _git(root, "add", ".")
    subprocess.run(
        [
            "git",
            "-c",
            "user.email=test@example.invalid",
            "-c",
            "user.name=Test",
            "commit",
            "-m",
            "fixture",
        ],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    return root


def _run_gate(root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", "scripts/verify_strategy_source_clean.sh"],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )


def test_shell_gate_accepts_clean_exact_source(tmp_path: Path):
    root = _repo(tmp_path)
    result = _run_gate(root)
    assert result.returncode == 0
    assert "STRATEGY_SOURCE_SHA=" in result.stdout


def test_shell_gate_blocks_tracked_edit_before_python(tmp_path: Path):
    root = _repo(tmp_path)
    (root / "signal_runner.py").write_text("VALUE = 2\n", encoding="utf-8")
    result = _run_gate(root)
    assert result.returncode != 0
    assert "tracked or untracked strategy source changes" in result.stderr






def test_shell_gate_blocks_tracked_root_startup_module_edit(tmp_path: Path):
    root = _repo(tmp_path)
    dashboard = root / "dashboard.py"
    dashboard.write_text("VALUE = 1\n", encoding="utf-8")
    _git(root, "add", "dashboard.py")
    subprocess.run(
        [
            "git",
            "-c",
            "user.email=test@example.invalid",
            "-c",
            "user.name=Test",
            "commit",
            "-m",
            "root startup fixture",
        ],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )

    dashboard.write_text("VALUE = 2\n", encoding="utf-8")
    result = _run_gate(root)

    assert result.returncode != 0
    assert "tracked or untracked strategy source changes" in result.stderr


def test_shell_gate_blocks_tracked_runtime_binding_verifier_edit(tmp_path: Path):
    root = _repo(tmp_path)
    verifier = root / "scripts" / "verify_exact_checkout_import.py"
    verifier.write_text("print('trusted')\n", encoding="utf-8")
    gate = root / "scripts" / "ensure_exact_checkout_runtime.sh"
    gate.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    _git(root, "add", "scripts/verify_exact_checkout_import.py", "scripts/ensure_exact_checkout_runtime.sh")
    subprocess.run(
        [
            "git",
            "-c",
            "user.email=test@example.invalid",
            "-c",
            "user.name=Test",
            "commit",
            "-m",
            "runtime gate fixture",
        ],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )

    verifier.write_text("print('tampered')\n", encoding="utf-8")
    result = _run_gate(root)

    assert result.returncode != 0
    assert "tracked or untracked strategy source changes" in result.stderr


def test_shell_gate_blocks_ignored_importable_startup_artifact(tmp_path: Path):
    root = _repo(tmp_path)
    (root / ".gitignore").write_text("sitecustomize.pyc\n", encoding="utf-8")
    _git(root, "add", ".gitignore")
    subprocess.run(
        [
            "git",
            "-c",
            "user.email=test@example.invalid",
            "-c",
            "user.name=Test",
            "commit",
            "-m",
            "ignore fixture",
        ],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    (root / "sitecustomize.pyc").write_bytes(b"not-real-bytecode")
    result = _run_gate(root)
    assert result.returncode != 0
    assert "ignored importable" in result.stderr




def test_shell_gate_blocks_untracked_root_ai_asset_platform_shadow(tmp_path: Path):
    root = _repo(tmp_path)
    shadow = root / "ai_asset_platform"
    shadow.mkdir()
    (shadow / "__init__.py").write_text("VALUE = 'shadow'\n", encoding="utf-8")

    result = _run_gate(root)

    assert result.returncode != 0
    assert "tracked or untracked strategy source changes" in result.stderr


def test_shell_gate_blocks_ignored_pycache_bytecode(tmp_path: Path):
    root = _repo(tmp_path)
    (root / ".gitignore").write_text("__pycache__/\n", encoding="utf-8")
    _git(root, "add", ".gitignore")
    subprocess.run(
        [
            "git",
            "-c",
            "user.email=test@example.invalid",
            "-c",
            "user.name=Test",
            "commit",
            "-m",
            "ignore pycache fixture",
        ],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    cache = root / "src" / "shadow" / "__pycache__"
    cache.mkdir(parents=True)
    (cache / "payload.cpython-313.pyc").write_bytes(b"executable-cache")
    result = _run_gate(root)
    assert result.returncode != 0
    assert "ignored importable" in result.stderr


def test_promotion_wrapper_invalidates_stale_pass_when_shell_gate_blocks(tmp_path: Path):
    root = _repo(tmp_path)
    shutil.copy2(
        Path(__file__).parents[1] / "strategy_promotion_policy_once.sh",
        root / "strategy_promotion_policy_once.sh",
    )
    (root / ".gitignore").write_text("__pycache__/\nresults/\n", encoding="utf-8")
    _git(root, "add", ".gitignore", "strategy_promotion_policy_once.sh")
    subprocess.run(
        [
            "git",
            "-c",
            "user.email=test@example.invalid",
            "-c",
            "user.name=Test",
            "commit",
            "-m",
            "wrapper fixture",
        ],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    cache = root / "src" / "shadow" / "__pycache__"
    cache.mkdir(parents=True)
    (cache / "payload.cpython-313.pyc").write_bytes(b"executable-cache")
    results = root / "results"
    results.mkdir()
    decision = results / "strategy_promotion_decision_latest.json"
    decision.write_text(
        json.dumps(
            {
                "status": "PROMOTION_POLICY_PASS",
                "promotion_policy_passed": True,
                "normal_live_strategy_deployment_allowed": False,
            }
        ),
        encoding="utf-8",
    )
    env = dict(os.environ)
    env["AI_ASSET_PLATFORM_ROOT"] = str(root)
    completed = subprocess.run(
        ["bash", "strategy_promotion_policy_once.sh"],
        cwd=root,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode != 0
    payload = json.loads(decision.read_text(encoding="utf-8"))
    assert payload["status"] == "PROMOTION_POLICY_BLOCKED"
    assert payload["promotion_policy_passed"] is False
    assert payload["normal_live_strategy_deployment_allowed"] is False
    assert payload["live_trading"] == "PROHIBITED"


def test_strategy_operational_wrappers_disable_python_bytecode_before_python_tools():
    root = Path(__file__).parents[1]
    for name in (
        "start.sh",
        "strategy_promotion_policy_once.sh",
        "ibkr_strategy_profitability_evidence_once.sh",
        "ibkr_verified_paper_runtime_once.sh",
    ):
        source = (root / name).read_text(encoding="utf-8")
        export_index = source.find("export PYTHONDONTWRITEBYTECODE=1")
        assert export_index >= 0, name
        for marker in (
            "source .venv/bin/activate",
            "bash scripts/ensure_exact_checkout_runtime.sh",
            "pytest -q",
            "python -m ",
        ):
            marker_index = source.find(marker)
            if marker_index >= 0:
                assert export_index < marker_index, (name, marker)


def test_python_dont_write_bytecode_environment_prevents_import_cache(tmp_path: Path):
    package = tmp_path / "samplepkg"
    package.mkdir()
    (package / "__init__.py").write_text("VALUE = 7\n", encoding="utf-8")
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONPATH"] = str(tmp_path)
    completed = subprocess.run(
        [
            "python",
            "-c",
            "import samplepkg; assert samplepkg.VALUE == 7",
        ],
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    assert not (package / "__pycache__").exists()


def test_start_sh_verifies_exact_checkout_before_repository_python():
    root = Path(__file__).parents[1]
    source = (root / "start.sh").read_text(encoding="utf-8")

    activate_index = source.index("source .venv/bin/activate")
    first_unset_index = source.index("unset PYTHONPATH PYTHONHOME")
    first_verify_index = source.index("bash scripts/ensure_exact_checkout_runtime.sh")

    assert activate_index < first_unset_index < first_verify_index

    safe_env_index = source.index("python scripts/load_start_env.py .env")
    restore_path_index = source.index('PATH="$TRUSTED_PYTHON_PATH"', safe_env_index)
    second_unset_index = source.index("unset PYTHONPATH PYTHONHOME", safe_env_index)
    second_verify_index = source.index(
        "bash scripts/ensure_exact_checkout_runtime.sh",
        first_verify_index + 1,
    )

    assert safe_env_index < restore_path_index < second_unset_index < second_verify_index

    for marker in (
        "python main_simple_step8.py",
        "python -m signal_runner",
        "python -m dashboard",
        "python -m candidate_dashboard",
        "python -m change_tracker",
    ):
        assert second_verify_index < source.index(marker), marker


def test_start_sh_restores_trusted_path_after_env_source():
    root = Path(__file__).parents[1]
    source = (root / "start.sh").read_text(encoding="utf-8")

    capture_index = source.index('TRUSTED_PYTHON_PATH="$PATH"')
    safe_env_index = source.index("python scripts/load_start_env.py .env")
    restore_index = source.index('PATH="$TRUSTED_PYTHON_PATH"', safe_env_index)

    assert capture_index < safe_env_index < restore_index
    assert "source .env" not in source


def test_shell_gate_blocks_untracked_root_native_module_shadow(tmp_path: Path):
    root = _repo(tmp_path)
    (root / "dashboard.cpython-313-x86_64-linux-gnu.so").write_bytes(b"shadow")

    result = _run_gate(root)

    assert result.returncode != 0
    assert "tracked or untracked strategy source changes" in result.stderr


def test_shell_gate_blocks_dirty_operational_test_code(tmp_path: Path):
    root = _repo(tmp_path)
    tests = root / "tests"
    tests.mkdir()
    target = tests / "test_strategy_promotion_policy.py"
    target.write_text("VALUE = 1\n", encoding="utf-8")
    _git(root, "add", "tests/test_strategy_promotion_policy.py")
    subprocess.run(
        [
            "git",
            "-c",
            "user.email=test@example.invalid",
            "-c",
            "user.name=Test",
            "commit",
            "-m",
            "test trust-boundary fixture",
        ],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    target.write_text("VALUE = 2\n", encoding="utf-8")

    result = _run_gate(root)

    assert result.returncode != 0
    assert "tracked or untracked strategy source changes" in result.stderr


def test_start_sh_blocks_env_shell_function_injection(tmp_path: Path):
    root = _repo(tmp_path)
    shutil.copy2(Path(__file__).parents[1] / "start.sh", root / "start.sh")
    ensure = root / "scripts" / "ensure_exact_checkout_runtime.sh"
    ensure.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    verifier = root / "scripts" / "verify_exact_checkout_import.py"
    verifier.write_text("raise SystemExit(0)\n", encoding="utf-8")
    loader = root / "scripts" / "load_start_env.py"
    shutil.copy2(Path(__file__).parents[1] / "scripts" / "load_start_env.py", loader)
    (root / ".gitignore").write_text(".venv/\n.env\n", encoding="utf-8")
    _git(
        root,
        "add",
        "start.sh",
        "scripts/ensure_exact_checkout_runtime.sh",
        "scripts/verify_exact_checkout_import.py",
        "scripts/load_start_env.py",
        ".gitignore",
    )
    subprocess.run(
        [
            "git",
            "-c",
            "user.email=test@example.invalid",
            "-c",
            "user.name=Test",
            "commit",
            "-m",
            "start fixture",
        ],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )

    bindir = root / ".venv" / "bin"
    bindir.mkdir(parents=True)
    marker = root / "application-ran"
    python = bindir / "python"
    python.write_text(
        "#!/usr/bin/env bash\n"
        "if [[ \"$1\" == \"scripts/load_start_env.py\" ]]; then "
        f'exec "{sys.executable}" "$@"\n'
        "fi\n"
        "if [[ \"$*\" == *\"main_simple_step8.py\"* ]]; then "
        f"touch {marker!s}; fi\n"
        "exit 0\n",
        encoding="utf-8",
    )
    python.chmod(0o755)
    activate = bindir / "activate"
    activate.write_text(
        f'deactivate() {{ :; }}\nexport PATH="{bindir!s}:$PATH"\n',
        encoding="utf-8",
    )
    pytest = bindir / "pytest"
    pytest.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    pytest.chmod(0o755)

    (root / ".env").write_text(
        "python() { return 0; }\n",
        encoding="utf-8",
    )

    completed = subprocess.run(
        ["bash", "start.sh"],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode != 0
    assert "changed shell functions" in completed.stderr
    assert not marker.exists()


def test_promotion_wrapper_preserves_completed_detailed_blocked_decision(tmp_path: Path):
    root = _repo(tmp_path)
    shutil.copy2(
        Path(__file__).parents[1] / "strategy_promotion_policy_once.sh",
        root / "strategy_promotion_policy_once.sh",
    )
    ensure = root / "scripts" / "ensure_exact_checkout_runtime.sh"
    ensure.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    verifier = root / "scripts" / "verify_exact_checkout_import.py"
    verifier.write_text("raise SystemExit(0)\n", encoding="utf-8")
    (root / ".gitignore").write_text(".venv/\nresults/\n", encoding="utf-8")
    _git(
        root,
        "add",
        "strategy_promotion_policy_once.sh",
        "scripts/ensure_exact_checkout_runtime.sh",
        "scripts/verify_exact_checkout_import.py",
        ".gitignore",
    )
    subprocess.run(
        [
            "git",
            "-c",
            "user.email=test@example.invalid",
            "-c",
            "user.name=Test",
            "commit",
            "-m",
            "promotion wrapper fixture",
        ],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )

    bindir = root / ".venv" / "bin"
    bindir.mkdir(parents=True)
    activate = bindir / "activate"
    activate.write_text(f'export PATH="{bindir!s}:$PATH"\n', encoding="utf-8")
    pytest = bindir / "pytest"
    pytest.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    pytest.chmod(0o755)
    python = bindir / "python"
    python.write_text(
        "#!/usr/bin/env bash\n"
        "mkdir -p results\n"
        "cat > results/strategy_promotion_decision_latest.json <<'EOF'\n"
        '{"status":"PROMOTION_POLICY_BLOCKED","policy_version":"test-v1",'
        '"promotion_policy_passed":false,"normal_live_strategy_deployment_allowed":false,'
        '"blockers":["minimum closed trades not met"],"live_trading":"PROHIBITED"}\n'
        "EOF\n"
        "exit 1\n",
        encoding="utf-8",
    )
    python.chmod(0o755)

    completed = subprocess.run(
        ["bash", "strategy_promotion_policy_once.sh"],
        cwd=root,
        env={**os.environ, "AI_ASSET_PLATFORM_ROOT": str(root)},
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 1
    payload = json.loads(
        (root / "results" / "strategy_promotion_decision_latest.json").read_text(
            encoding="utf-8"
        )
    )
    assert payload["policy_version"] == "test-v1"
    assert payload["blockers"] == ["minimum closed trades not met"]


def test_safe_start_env_loader_accepts_documented_literal_values(tmp_path: Path):
    env_file = tmp_path / ".env"
    password_key = "APP_" + "PASSWORD"
    env_file.write_text(
        "EMAIL_ADDRESS='user@example.com'\n"
        + f"{password_key}='fixture value'\n"
        + "AI_ASSET_ENABLE_IBKR_PAPER=true\n",
        encoding="utf-8",
    )
    completed = subprocess.run(
        [
            "python",
            str(Path(__file__).parents[1] / "scripts" / "load_start_env.py"),
            str(env_file),
        ],
        check=False,
        capture_output=True,
    )
    assert completed.returncode == 0, completed.stderr.decode("utf-8")
    parts = completed.stdout.split(b"\0")
    assert parts[-1] == b""
    pairs = dict(zip(parts[0::2], parts[1::2]))
    assert pairs[b"EMAIL_ADDRESS"] == b"user@example.com"
    assert pairs[b"APP_PASSWORD"] == b"fixture value"
    assert pairs[b"AI_ASSET_ENABLE_IBKR_PAPER"] == b"true"


def test_safe_start_env_loader_rejects_shell_code_and_dangerous_unknown_keys(tmp_path: Path):
    loader = str(Path(__file__).parents[1] / "scripts" / "load_start_env.py")
    for payload in (
        "python() { return 0; }\n",
        "BASH_ENV=/tmp/pwn\n",
        "LD_PRELOAD=/tmp/pwn.so\n",
        "PATH=/tmp/pwn\n",
    ):
        env_file = tmp_path / ".env"
        env_file.write_text(payload, encoding="utf-8")
        completed = subprocess.run(
            ["python", loader, str(env_file)],
            check=False,
            capture_output=True,
            text=True,
        )
        assert completed.returncode != 0, payload
        assert "BLOCKED: unsafe .env" in completed.stderr

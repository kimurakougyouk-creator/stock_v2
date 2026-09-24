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


def test_strategy_source_shell_gate_has_valid_bash_syntax():
    completed = subprocess.run(
        ["bash", "-n", str(SCRIPT)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr


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


def test_shell_gate_disables_repo_configured_fsmonitor_hook(tmp_path: Path):
    root = _repo(tmp_path)
    marker = tmp_path / "fsmonitor-ran.marker"
    hook = tmp_path / "fsmonitor-hook.sh"
    hook.write_text(
        "#!/bin/sh\n"
        f"printf ran > {marker!s}\n"
        "exit 0\n",
        encoding="utf-8",
    )
    hook.chmod(0o755)
    _git(root, "config", "core.fsmonitor", str(hook))

    result = _run_gate(root)

    assert result.returncode == 0, result.stderr
    assert not marker.exists()








def test_shell_gate_blocks_tracked_ticker_universe_edit(tmp_path: Path):
    root = _repo(tmp_path)
    tickers = root / "tickers.csv"
    tickers.write_text("Ticker\n9432.T\n", encoding="utf-8")
    _git(root, "add", "tickers.csv")
    subprocess.run(
        [
            "git",
            "-c",
            "user.email=test@example.invalid",
            "-c",
            "user.name=Test",
            "commit",
            "-m",
            "ticker universe fixture",
        ],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    tickers.write_text("Ticker\n9432.T\nAAPL\n", encoding="utf-8")

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
    shutil.copy2(
        Path(__file__).parents[1]
        / "scripts"
        / "strategy_promotion_policy_once_sanitized.sh",
        root / "scripts" / "strategy_promotion_policy_once_sanitized.sh",
    )
    (root / ".gitignore").write_text("__pycache__/\nresults/\n", encoding="utf-8")
    _git(
        root,
        "add",
        ".gitignore",
        "strategy_promotion_policy_once.sh",
        "scripts/strategy_promotion_policy_once_sanitized.sh",
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
    (root / "strategy_promotion_policy_once.sh").chmod(0o755)
    completed = subprocess.run(
        [str(root / "strategy_promotion_policy_once.sh")],
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
    pairs = (
        ("start.sh", None),
        (
            "strategy_promotion_policy_once.sh",
            "scripts/strategy_promotion_policy_once_sanitized.sh",
        ),
        (
            "ibkr_strategy_profitability_evidence_once.sh",
            "scripts/ibkr_strategy_profitability_evidence_once_sanitized.sh",
        ),
        (
            "ibkr_verified_paper_runtime_once.sh",
            "scripts/ibkr_verified_paper_runtime_once_sanitized.sh",
        ),
    )
    for name, body_name in pairs:
        source = (root / name).read_text(encoding="utf-8")
        if body_name is not None:
            source += "\n" + (root / body_name).read_text(encoding="utf-8")
        bytecode_index = source.find("PYTHONDONTWRITEBYTECODE=1")
        assert bytecode_index >= 0, name
        for marker in (
            "source .venv/bin/activate",
            "bash scripts/ensure_exact_checkout_runtime.sh",
            "pytest -q",
            "python -m ",
        ):
            marker_index = source.find(marker)
            if marker_index >= 0:
                assert bytecode_index < marker_index, (name, marker)


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
    launcher = (root / "start.sh").read_text(encoding="utf-8")
    source = (root / "scripts" / "start_sanitized.sh").read_text(encoding="utf-8")

    assert "AI_ASSET_START_SANITIZED" not in launcher
    assert "exec /usr/bin/env -i" in launcher
    assert "/bin/bash --noprofile --norc" in launcher
    assert "scripts/start_sanitized.sh" in launcher
    assert "source .venv/bin/activate" not in source
    assert 'VENV_PYTHON="$PWD/.venv/bin/python"' in source

    first_source_gate = source.index("/bin/bash scripts/verify_strategy_source_clean.sh")
    first_runtime_gate = source.index("\nverify_exact_checkout_runtime\n")
    safe_env_index = source.index('"$VENV_PYTHON" scripts/load_start_env.py .env')
    second_source_gate = source.index(
        "/bin/bash scripts/verify_strategy_source_clean.sh",
        first_source_gate + 1,
    )
    second_runtime_gate = source.index(
        "\nverify_exact_checkout_runtime\n",
        first_runtime_gate + 1,
    )
    first_application = source.index("run_isolated main_simple_step8.py")

    assert (
        first_source_gate
        < first_runtime_gate
        < safe_env_index
        < second_source_gate
        < second_runtime_gate
        < first_application
    )


def test_start_sh_rechecks_full_source_boundary_after_setup_and_env_data():
    root = Path(__file__).parents[1]
    source = (root / "scripts" / "start_sanitized.sh").read_text(encoding="utf-8")

    first_gate = source.index("/bin/bash scripts/verify_strategy_source_clean.sh")
    safe_env = source.index('"$VENV_PYTHON" scripts/load_start_env.py .env')
    second_gate = source.index(
        "/bin/bash scripts/verify_strategy_source_clean.sh",
        first_gate + 1,
    )
    first_application = source.index("run_isolated main_simple_step8.py")

    assert first_gate < safe_env < second_gate < first_application


def test_start_sh_sanitizes_inherited_command_environment_before_gates():
    root = Path(__file__).parents[1]
    launcher = (root / "start.sh").read_text(encoding="utf-8")
    source = (root / "scripts" / "start_sanitized.sh").read_text(encoding="utf-8")

    assert "AI_ASSET_START_SANITIZED" not in launcher
    assert "exec /usr/bin/env -i" in launcher
    assert "scripts/start_sanitized.sh" in launcher
    assert launcher.startswith("#!/bin/sh\n")
    assert "explicit Bash invocation is unsupported" in launcher
    assert 'export PATH="/usr/local/bin:/usr/bin:/bin"' in source
    assert "source .venv/bin/activate" not in source
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
    inner = root / "scripts" / "start_sanitized.sh"
    shutil.copy2(Path(__file__).parents[1] / "scripts" / "start_sanitized.sh", inner)
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
        "scripts/start_sanitized.sh",
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

    (root / "start.sh").chmod(0o755)
    completed = subprocess.run(
        [str(root / "start.sh")],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode != 0
    assert "BLOCKED: unsafe .env" in completed.stderr
    assert not marker.exists()


def test_promotion_wrapper_preserves_completed_detailed_blocked_decision(tmp_path: Path):
    root = _repo(tmp_path)
    repo_root = Path(__file__).parents[1]
    shutil.copy2(
        repo_root / "strategy_promotion_policy_once.sh",
        root / "strategy_promotion_policy_once.sh",
    )
    shutil.copy2(
        repo_root / "scripts" / "strategy_promotion_policy_once_sanitized.sh",
        root / "scripts" / "strategy_promotion_policy_once_sanitized.sh",
    )
    shutil.copy2(
        repo_root / "scripts" / "run_isolated_venv_python.py",
        root / "scripts" / "run_isolated_venv_python.py",
    )
    verifier = root / "scripts" / "verify_exact_checkout_import.py"
    verifier.write_text("raise SystemExit(0)\n", encoding="utf-8")

    package = root / "src" / "ai_asset_platform" / "reports"
    package.mkdir(parents=True)
    (root / "src" / "ai_asset_platform" / "__init__.py").write_text(
        "", encoding="utf-8"
    )
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "strategy_promotion_policy.py").write_text(
        "from pathlib import Path\n"
        "import json\n"
        "Path('results').mkdir(exist_ok=True)\n"
        "Path('results/strategy_promotion_decision_latest.json').write_text("
        "json.dumps({"
        "'status':'PROMOTION_POLICY_BLOCKED',"
        "'policy_version':'test-v1',"
        "'promotion_policy_passed':False,"
        "'normal_live_strategy_deployment_allowed':False,"
        "'blockers':['minimum closed trades not met'],"
        "'live_trading':'PROHIBITED'"
        "}), encoding='utf-8')\n"
        "raise SystemExit(1)\n",
        encoding="utf-8",
    )

    (root / ".gitignore").write_text(".venv/\nresults/\n", encoding="utf-8")
    _git(
        root,
        "add",
        "strategy_promotion_policy_once.sh",
        "scripts/strategy_promotion_policy_once_sanitized.sh",
        "scripts/run_isolated_venv_python.py",
        "scripts/verify_exact_checkout_import.py",
        "src/ai_asset_platform/__init__.py",
        "src/ai_asset_platform/reports/__init__.py",
        "src/ai_asset_platform/reports/strategy_promotion_policy.py",
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

    system_version = subprocess.check_output(
        [
            "/usr/bin/python3",
            "-I",
            "-S",
            "-c",
            "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')",
        ],
        text=True,
    ).strip()
    venv_bin = root / ".venv" / "bin"
    venv_bin.mkdir(parents=True, exist_ok=True)
    venv_python = venv_bin / "python"
    if not venv_python.exists():
        venv_python.symlink_to("/usr/bin/python3")
    site_packages = (
        root
        / ".venv"
        / "lib"
        / f"python{system_version}"
        / "site-packages"
    )
    pytest_pkg = site_packages / "pytest"
    pytest_pkg.mkdir(parents=True)
    init_file = pytest_pkg / "__init__.py"
    main_file = pytest_pkg / "__main__.py"
    init_file.write_text("", encoding="utf-8")
    main_file.write_text("raise SystemExit(0)\n", encoding="utf-8")
    dist = site_packages / "pytest-1.0.dist-info"
    dist.mkdir()
    import base64
    import hashlib
    record_lines = []
    for rel, path in (
        ("pytest/__init__.py", init_file),
        ("pytest/__main__.py", main_file),
    ):
        data = path.read_bytes()
        digest = base64.urlsafe_b64encode(
            hashlib.sha256(data).digest()
        ).rstrip(b"=").decode("ascii")
        record_lines.append(f"{rel},sha256={digest},{len(data)}")
    record_lines.append("pytest-1.0.dist-info/RECORD,,")
    (dist / "RECORD").write_text(
        "\n".join(record_lines) + "\n",
        encoding="utf-8",
    )

    (root / "strategy_promotion_policy_once.sh").chmod(0o755)
    completed = subprocess.run(
        [str(root / "strategy_promotion_policy_once.sh")],
        cwd=root,
        env={**os.environ, "AI_ASSET_PLATFORM_ROOT": str(root)},
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 1, completed.stderr
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
        + "AI_PROVIDER=gemini\n"
        + "GEMINI_API_KEY='fixture-gemini-key'\n"
        + "GEMINI_MODEL=gemini-test-model\n"
        + "OPENAI_MODEL=gpt-test-model\n"
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
    assert pairs[b"AI_PROVIDER"] == b"gemini"
    assert pairs[b"GEMINI_API_KEY"] == b"fixture-gemini-key"
    assert pairs[b"GEMINI_MODEL"] == b"gemini-test-model"
    assert pairs[b"OPENAI_MODEL"] == b"gpt-test-model"
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


def test_shell_gate_blocks_untracked_root_package_shadow(tmp_path: Path):
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
            "root module fixture",
        ],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    shadow = root / "dashboard"
    shadow.mkdir()
    (shadow / "__init__.py").write_text("VALUE = 'shadow'\n", encoding="utf-8")

    result = _run_gate(root)

    assert result.returncode != 0
    assert "tracked or untracked strategy source changes" in result.stderr




def test_shell_gate_blocks_third_party_root_symlink_shadow(tmp_path: Path):
    root = _repo(tmp_path)
    outside = tmp_path / "outside-ibapi"
    outside.mkdir()
    (outside / "__init__.py").write_text("VALUE = 'shadow'\n", encoding="utf-8")
    (root / "ibapi").symlink_to(outside, target_is_directory=True)

    result = _run_gate(root)

    assert result.returncode != 0
    assert "root-level symlink" in result.stderr


def test_shell_gate_blocks_external_root_package_symlink_shadow(tmp_path: Path):
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
            "root symlink fixture",
        ],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    outside = tmp_path / "outside-dashboard"
    outside.mkdir()
    (outside / "__init__.py").write_text("VALUE = 'shadow'\n", encoding="utf-8")
    (root / "dashboard").symlink_to(outside, target_is_directory=True)

    result = _run_gate(root)

    assert result.returncode != 0
    assert "root module symlink/package shadow" in result.stderr


def test_start_and_run_entrypoints_use_direct_posix_boundary():
    root = Path(__file__).parents[1]
    start = (root / "start.sh").read_text(encoding="utf-8")
    run = (root / "scripts" / "run.sh").read_text(encoding="utf-8")
    readme = (root / "README.md").read_text(encoding="utf-8")

    assert start.startswith("#!/bin/sh\n")
    assert run.startswith("#!/bin/sh\n")
    assert "explicit Bash invocation is unsupported" in start
    assert "explicit Bash invocation is unsupported" in run
    assert "./scripts/run.sh" in readme


def test_shell_gate_blocks_root_pycache_bytecode(tmp_path: Path):
    root = _repo(tmp_path)
    cache = root / "__pycache__"
    cache.mkdir()
    (cache / "signal_runner.cpython-313.pyc").write_bytes(b"forged")

    result = _run_gate(root)

    assert result.returncode != 0



@pytest.mark.parametrize(
    "relative_path",
    (
        "scripts/verify_live_ibapi_runtime.py",
        "scripts/live_ibapi_manifest.json",
    ),
)
def test_shell_gate_blocks_ibapi_trust_anchor_edit(tmp_path: Path, relative_path: str):
    root = _repo(tmp_path)
    target = root / relative_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("trusted\n", encoding="utf-8")
    _git(root, "add", relative_path)
    subprocess.run(
        [
            "git",
            "-c",
            "user.email=test@example.invalid",
            "-c",
            "user.name=Test",
            "commit",
            "-m",
            "ibapi trust anchor fixture",
        ],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )

    target.write_text("tampered\n", encoding="utf-8")
    result = _run_gate(root)

    assert result.returncode != 0
    assert "tracked or untracked strategy source changes" in result.stderr

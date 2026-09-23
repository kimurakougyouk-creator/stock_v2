from pathlib import Path
import json
import os
import shutil
import subprocess


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
    unset_index = source.index("unset PYTHONPATH")
    verify_index = source.index("bash scripts/ensure_exact_checkout_runtime.sh")

    assert activate_index < unset_index < verify_index

    for marker in (
        "python setup_wizard.py",
        "python main_simple_step8.py",
        "python -m signal_runner",
        "python -m dashboard",
        "python -m candidate_dashboard",
        "python -m change_tracker",
    ):
        assert verify_index < source.index(marker), marker

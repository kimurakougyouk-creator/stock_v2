from pathlib import Path
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

from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def test_current_tracked_tree_passes_secret_scan():
    result = subprocess.run(
        [sys.executable, "scripts/check_secrets.py"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "SECRET SCAN: PASSED" in result.stdout

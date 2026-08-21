import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_backup_and_save_artifacts_are_not_tracked():
    result = subprocess.run(
        ["git", "ls-files"], cwd=ROOT, check=True, capture_output=True, text=True
    )
    tracked = result.stdout.splitlines()
    assert not any(path == "backup" or path.startswith("backup/") for path in tracked)
    assert not any(path.endswith(".save") for path in tracked)

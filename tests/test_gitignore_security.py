from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_sensitive_and_backup_paths_remain_ignored():
    lines = {
        line.strip()
        for line in (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    for required in {".env", ".env.*", "*.secret", "backup/", "*.save"}:
        assert required in lines

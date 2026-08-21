"""Fail CI when likely credentials are committed to tracked text files.

This intentionally uses only the Python standard library so it can run in the
existing pytest/CI environment without adding a third-party dependency.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKIP_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".xlsx", ".zip", ".pdf", ".pyc"}
SKIP_PATH_PARTS = {".git", ".venv", "venv", "__pycache__", ".pytest_cache"}

PATTERNS = {
    "private key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "GitHub token": re.compile(r"\b(?:ghp|github_pat)_[A-Za-z0-9_]{20,}\b"),
    "OpenAI-style API key": re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    "AWS access key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
}

# Assignment-like credential checks. Placeholder/example values are allowed.
ASSIGNMENT = re.compile(
    r"(?i)\b(password|passwd|app_password|api_key|secret|token)\b\s*[=:]\s*['\"]([^'\"]+)['\"]"
)
PLACEHOLDER_MARKERS = (
    "example", "dummy", "placeholder", "changeme", "your_", "<", "${", "os.getenv", "none", "test",
)


def tracked_files() -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "-z"], cwd=ROOT, check=True, capture_output=True
    )
    return [ROOT / p.decode() for p in result.stdout.split(b"\0") if p]


def main() -> int:
    findings: list[str] = []
    for path in tracked_files():
        rel = path.relative_to(ROOT)
        if any(part in SKIP_PATH_PARTS for part in rel.parts) or path.suffix.lower() in SKIP_SUFFIXES:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for label, pattern in PATTERNS.items():
            if pattern.search(text):
                findings.append(f"{rel}: detected {label}")
        for match in ASSIGNMENT.finditer(text):
            value = match.group(2).strip().lower()
            if len(value) >= 8 and not any(marker in value for marker in PLACEHOLDER_MARKERS):
                findings.append(f"{rel}: suspicious hard-coded credential assignment ({match.group(1)})")
    if findings:
        print("SECRET SCAN: FAILED")
        for finding in sorted(set(findings)):
            print(f"- {finding}")
        return 1
    print("SECRET SCAN: PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())

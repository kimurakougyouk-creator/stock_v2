from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKIP_DIRS = {'.git', '.venv', 'venv', '__pycache__', '.pytest_cache', '.mypy_cache', 'node_modules'}
TEXT_SUFFIXES = {'.py', '.md', '.txt', '.yml', '.yaml', '.json', '.toml', '.ini', '.cfg', '.sh', '.env', '.example'}

PATTERNS = {
    'private_key': re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'),
    'github_token': re.compile(r'\b(?:ghp|github_pat)_[A-Za-z0-9_]{20,}\b'),
    'openai_key': re.compile(r'\bsk-[A-Za-z0-9_-]{20,}\b'),
    'aws_access_key': re.compile(r'\bAKIA[0-9A-Z]{16}\b'),
    'hardcoded_app_password': re.compile(r'(?i)(?:APP_PASSWORD|app_password)\s*=\s*[\"\'][^\"\'\n]{8,}[\"\']'),
}


def tracked_files() -> list[Path]:
    result = subprocess.run(
        ['git', 'ls-files'], cwd=ROOT, check=True, capture_output=True, text=True
    )
    return [ROOT / line for line in result.stdout.splitlines() if line]


def should_scan(path: Path) -> bool:
    try:
        rel = path.relative_to(ROOT)
    except ValueError:
        return False
    if any(part in SKIP_DIRS for part in rel.parts):
        return False
    return path.suffix.lower() in TEXT_SUFFIXES or path.name.startswith('.env')


def main() -> int:
    findings: list[str] = []
    for path in tracked_files():
        if not path.is_file() or not should_scan(path):
            continue
        try:
            text = path.read_text(encoding='utf-8')
        except (UnicodeDecodeError, OSError):
            continue
        rel = path.relative_to(ROOT)
        for name, pattern in PATTERNS.items():
            for match in pattern.finditer(text):
                line = text.count('\n', 0, match.start()) + 1
                findings.append(f'{rel}:{line}: {name}')

    if findings:
        print('SECRET SCAN: FAILED')
        for finding in findings:
            print(f'- {finding}')
        return 1

    print('SECRET SCAN: PASS')
    return 0


if __name__ == '__main__':
    sys.exit(main())

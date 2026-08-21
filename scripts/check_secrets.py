from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKIP_DIRS = {'.git', '.venv', 'venv', '__pycache__', '.pytest_cache', 'node_modules'}
PLACEHOLDER_PREFIXES = ('test-', 'fake-', 'dummy-', 'example-', 'app-password')
PATTERNS = {
    'private_key': re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'),
    'github_token': re.compile(r'\b(?:ghp|github_pat)_[A-Za-z0-9_]{20,}\b'),
    'openai_key': re.compile(r'\bsk-[A-Za-z0-9_-]{20,}\b'),
    'aws_access_key': re.compile(r'\bAKIA[0-9A-Z]{16}\b'),
}
CREDENTIAL_ASSIGNMENT = re.compile(
    r'(?i)\b(?:password|passwd|api[_-]?key|token|app_password)\b\s*=\s*[\"\']([^\"\'\n]{8,})[\"\']'
)


def tracked_files() -> list[Path]:
    result = subprocess.run(['git', 'ls-files'], cwd=ROOT, check=True, capture_output=True, text=True)
    return [ROOT / name for name in result.stdout.splitlines() if name]


def is_placeholder(value: str) -> bool:
    normalized = value.strip().lower()
    return normalized.startswith(PLACEHOLDER_PREFIXES)


def main() -> int:
    findings: list[str] = []
    for path in tracked_files():
        rel = path.relative_to(ROOT)
        if any(part in SKIP_DIRS for part in rel.parts) or not path.is_file():
            continue
        try:
            text = path.read_text(encoding='utf-8')
        except (UnicodeDecodeError, OSError):
            continue

        for label, pattern in PATTERNS.items():
            for match in pattern.finditer(text):
                line = text.count('\n', 0, match.start()) + 1
                findings.append(f'{rel}:{line}: {label}')

        for match in CREDENTIAL_ASSIGNMENT.finditer(text):
            if is_placeholder(match.group(1)):
                continue
            line = text.count('\n', 0, match.start()) + 1
            findings.append(f'{rel}:{line}: hardcoded_credential')

    if findings:
        print('SECRET SCAN: FAILED')
        print('\n'.join(f'- {item}' for item in findings))
        return 1

    print('SECRET SCAN: PASS')
    return 0


if __name__ == '__main__':
    sys.exit(main())

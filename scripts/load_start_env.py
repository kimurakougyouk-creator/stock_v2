"""Safely parse the small, documented start.sh .env contract.

The file is treated strictly as data. Shell commands, functions, redirections,
unknown keys, duplicate keys, and malformed quoting fail closed.
"""
from __future__ import annotations

from pathlib import Path
import re
import shlex
import sys

_ALLOWED_KEYS = frozenset(
    {
        "EMAIL_ADDRESS",
        "APP_PASSWORD",
        "OPENAI_API_KEY",
        "AI_ASSET_ENABLE_IBKR_PAPER",
        "AI_ASSET_ENABLE_LIVE_TRADING",
        "AI_ASSET_LIVE_TRADING_UNLOCKED",
        "IBKR_PAPER_MONITOR_EMAIL_ALERTS",
        "IBKR_PAPER_MONITOR_EMAIL_COOLDOWN_HOURS",
        "IBKR_PAPER_MONITOR_MAX_RUNTIME_AGE_HOURS",
        "IBKR_PAPER_MONITOR_MAX_HISTORY_BYTES",
    }
)
_KEY_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")


class SafeEnvError(ValueError):
    pass


def parse_start_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8", errors="strict").splitlines()
    except (OSError, UnicodeError) as exc:
        raise SafeEnvError(f"cannot read .env safely: {exc}") from exc

    for line_number, raw in enumerate(lines, start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].lstrip()
        if "=" not in line:
            raise SafeEnvError(
                f".env line {line_number} is not a KEY=VALUE assignment"
            )
        key, raw_value = line.split("=", 1)
        key = key.strip()
        if not _KEY_RE.fullmatch(key) or key not in _ALLOWED_KEYS:
            raise SafeEnvError(
                f".env line {line_number} uses an unapproved key: {key or '<empty>'}"
            )
        if key in values:
            raise SafeEnvError(f".env key is duplicated: {key}")

        text = raw_value.strip()
        if not text:
            value = ""
        else:
            try:
                tokens = shlex.split(text, comments=False, posix=True)
            except ValueError as exc:
                raise SafeEnvError(
                    f".env line {line_number} has malformed quoting"
                ) from exc
            if len(tokens) != 1:
                raise SafeEnvError(
                    f".env line {line_number} must contain one literal value"
                )
            value = tokens[0]
        if "\x00" in value:
            raise SafeEnvError(f".env line {line_number} contains NUL")
        values[key] = value
    return values


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1:
        print("usage: load_start_env.py PATH", file=sys.stderr)
        return 2
    try:
        values = parse_start_env(Path(args[0]))
    except SafeEnvError as exc:
        print(f"BLOCKED: unsafe .env: {exc}", file=sys.stderr)
        return 2

    out = sys.stdout.buffer
    for key in sorted(values):
        out.write(key.encode("utf-8"))
        out.write(b"\0")
        out.write(values[key].encode("utf-8"))
        out.write(b"\0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

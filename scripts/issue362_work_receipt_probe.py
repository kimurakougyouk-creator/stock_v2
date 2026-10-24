"""One-shot, bounded Work-audit receipt verification; requires local authenticated gh CLI.

No daemon, no scheduled tasks, no trade operations, no command execution from comments.
Default is read-only. --post explicitly sends at most one bounded receipt.
"""
import argparse
import json
import re
import subprocess
import sys

REPO = "kimurakougyouk-creator/stock_v2"
PR = 362
SOURCE = 6378440980
SHA_RE = re.compile(r"\bhead=([0-9a-f]{40})\b")
SOURCE_RE = re.compile(r"\bsource_comment_id=(\d+)\b")


def api(method, path, body=None):
    cmd = ["gh", "api", "--method", method, path]
    if body is not None:
        cmd.extend(["-f", "body=" + body])
    process = subprocess.run(cmd, capture_output=True, text=True, timeout=30, check=False)
    if process.returncode:
        raise RuntimeError("GitHub API failed; check authentication, permissions and network")
    return json.loads(process.stdout)


def _first_line(text):
    lines = text.splitlines()
    return lines[0] if lines else ""


def receipt_matches(body, sha):
    if not isinstance(body, str):
        return False
    first = _first_line(body)
    src = SOURCE_RE.search(first)
    head = SHA_RE.search(first)
    result = RESULT_RE.search(first)
    return (
        first.startswith(f"WORK_AUDIT_RECEIPT_V1 repo={REPO} pr={PR} ")
        and src is not None and int(src.group(1)) == SOURCE
        and head is not None and head.group(1) == sha
        and result is not None and result.group(1) == "VERIFIED"
    )


def _check_head(base, expected_sha):
    live = api("GET", f"{base}/pulls/{PR}")
    if (live.get("number") != PR or live.get("state") != "open"
            or live.get("draft") is not True
            or live.get("head", {}).get("sha") != expected_sha):
        raise ValueError("PR changed during audit; fail closed")


def run(post=False):
    base = f"repos/{REPO}"
    pr = api("GET", f"{base}/pulls/{PR}")
    audit = api("GET", f"{base}/issues/comments/{SOURCE}")
    if pr.get("number") != PR or pr.get("state") != "open" or pr.get("draft") is not True:
        raise ValueError("PR identity/state mismatch")
    if audit.get("id") != SOURCE:
        raise ValueError("wrong audit comment")
    first = _first_line(audit.get("body") or "")
    if not first.startswith(f"WORK_AUDIT_RESULT_V1 repo={REPO} pr={PR} head="):
        raise ValueError("invalid audit header")
    match = SHA_RE.search(first)
    sha = pr.get("head", {}).get("sha")
    if not match or match.group(1) != sha:
        raise ValueError("stale or invalid audit SHA")
    page = 1
    while page <= 50:
        items = api("GET", f"{base}/issues/{PR}/comments?per_page=100&page={page}")
        if not isinstance(items, list):
            raise ValueError("unexpected comments")
        existing = [x for x in items if receipt_matches(x.get("body"), sha)]
        if existing:
            print(f"RECEIPT_ALREADY_PRESENT id={existing[0]['id']} head={sha}")
            return
        if len(items) < 100:
            break
        page += 1
    else:
        raise ValueError("pagination limit; fail closed")
    if not post:
        print(f"VALIDATED_NO_RECEIPT head={sha}; read-only")
        return
    body = (f"WORK_AUDIT_RECEIPT_V1 repo={REPO} pr={PR} "
            f"source_comment_id={SOURCE} head={sha} result=VERIFIED\n\n"
            "Verified live GitHub audit record and PR HEAD using bounded local probe. "
            "Does not prove unattended Claude execution.")
    _check_head(base, sha)  # Revalidate as close to posting as possible.
    saved = api("POST", f"{base}/issues/{PR}/comments", body)
    check = api("GET", f"{base}/issues/comments/{saved['id']}")
    if check.get("body") != body:
        raise RuntimeError("receipt read-back mismatch")
    _check_head(base, sha)  # Never confirm a stale audit after a push.
    print(f"RECEIPT_POSTED id={saved['id']} head={sha}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--post", action="store_true")
    try:
        run(parser.parse_args().post)
    except (RuntimeError, ValueError, KeyError, IndexError, subprocess.TimeoutExpired) as exc:
        print(f"BLOCKED: {exc}", file=sys.stderr)
        sys.exit(1)

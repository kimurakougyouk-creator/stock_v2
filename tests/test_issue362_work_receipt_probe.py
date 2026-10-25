"""Unit tests for bounded Work audit receipt validation."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from issue362_work_receipt_probe import receipt_matches, SOURCE, REPO

SHA = "a" * 40

def test_exact_receipt_matches():
    msg = f"WORK_AUDIT_RECEIPT_V1 repo={REPO} pr=362 source_comment_id={SOURCE} head={SHA} result=VERIFIED"
    assert receipt_matches(msg, SHA)

@pytest.mark.parametrize("msg", [
    "not a receipt",
    "",
    f"WORK_AUDIT_RECEIPT_V1 repo={REPO} pr=362 source_comment_id=0 head={SHA} result=VERIFIED",
    f"WORK_AUDIT_RECEIPT_V1 repo={REPO} pr=362 source_comment_id={SOURCE} head=" + "b"*40,
    f"WORK_AUDIT_RECEIPT_V1 repo=other/repo pr=362 source_comment_id={SOURCE} head={SHA}",
    f"WORK_AUDIT_RECEIPT_V1 repo={REPO} pr=362 source_comment_id={SOURCE} head={SHA} result=HEAD_MISMATCH",
    f"WORK_AUDIT_RECEIPT_V1 repo={REPO} pr=362 source_comment_id={SOURCE} head={SHA} result=BLOCKED",
    f"WORK_AUDIT_RECEIPT_V1 repo={REPO} pr=362 source_comment_id={SOURCE} head={SHA}",
])
def test_rejects_mismatched_receipts(msg):
    assert not receipt_matches(msg, SHA)


def test_changed_head_is_rejected(monkeypatch):
    import issue362_work_receipt_probe as probe
    def fake_api(method, path, body=None):
        return {"number": 362, "state": "open", "draft": True,
                "head": {"sha": "b" * 40}}
    monkeypatch.setattr(probe, "api", fake_api)
    with pytest.raises(ValueError, match="changed"):
        probe._check_head("repos/" + REPO, SHA)


def _pr_fixture(sha):
    return {"number": 362, "state": "open", "draft": True, "head": {"sha": sha}}


def _audit_fixture(sha):
    return {
        "id": SOURCE,
        "body": f"WORK_AUDIT_RESULT_V1 repo={REPO} pr=362 head={sha}\n\nbody text",
    }


def test_run_detects_existing_receipt_and_never_posts_again(monkeypatch):
    # The probe's duplicate-prevention is not a local lock file (it has
    # none -- it is explicitly a one-shot, non-daemon tool): it asks
    # GitHub itself, authoritatively, whether a matching receipt already
    # exists before ever considering a post. Re-running this tool after
    # a receipt was already posted (e.g. the operator re-invokes it, or
    # it is invoked twice in quick succession) must detect that and
    # return without a second POST call, regardless of --post.
    import issue362_work_receipt_probe as probe

    calls = []
    existing_receipt_id = 999111
    existing_body = (
        f"WORK_AUDIT_RECEIPT_V1 repo={REPO} pr=362 "
        f"source_comment_id={SOURCE} head={SHA} result=VERIFIED"
    )

    def fake_api(method, path, body=None):
        calls.append((method, path, body))
        if path == f"repos/{REPO}/pulls/362":
            return _pr_fixture(SHA)
        if path == f"repos/{REPO}/issues/comments/{SOURCE}":
            return _audit_fixture(SHA)
        if path.startswith(f"repos/{REPO}/issues/362/comments?per_page=100&page=1"):
            return [{"id": existing_receipt_id, "body": existing_body}]
        raise AssertionError(f"unexpected api call: {method} {path}")

    monkeypatch.setattr(probe, "api", fake_api)
    probe.run(post=True)
    post_calls = [c for c in calls if c[0] == "POST"]
    assert post_calls == []


def test_run_is_read_only_by_default_even_with_no_existing_receipt(monkeypatch):
    import issue362_work_receipt_probe as probe

    calls = []

    def fake_api(method, path, body=None):
        calls.append((method, path, body))
        if path == f"repos/{REPO}/pulls/362":
            return _pr_fixture(SHA)
        if path == f"repos/{REPO}/issues/comments/{SOURCE}":
            return _audit_fixture(SHA)
        if path.startswith(f"repos/{REPO}/issues/362/comments"):
            return []
        raise AssertionError(f"unexpected api call: {method} {path}")

    monkeypatch.setattr(probe, "api", fake_api)
    probe.run(post=False)
    post_calls = [c for c in calls if c[0] == "POST"]
    assert post_calls == []


def test_run_fails_closed_on_pagination_limit(monkeypatch):
    # If the comments listing never shrinks below a full page across 50
    # pages (a sign something is wrong -- a real PR thread will not
    # genuinely hold 5000+ comments), this must fail closed rather than
    # silently stop paginating and treat whatever it saw as the full
    # picture.
    import issue362_work_receipt_probe as probe

    def fake_api(method, path, body=None):
        if path == f"repos/{REPO}/pulls/362":
            return _pr_fixture(SHA)
        if path == f"repos/{REPO}/issues/comments/{SOURCE}":
            return _audit_fixture(SHA)
        if path.startswith(f"repos/{REPO}/issues/362/comments"):
            return [{"id": i, "body": "unrelated"} for i in range(100)]
        raise AssertionError(f"unexpected api call: {method} {path}")

    monkeypatch.setattr(probe, "api", fake_api)
    with pytest.raises(ValueError, match="pagination limit"):
        probe.run(post=False)


def test_run_propagates_communication_failure_without_posting(monkeypatch):
    # api() raises RuntimeError on any non-zero `gh` exit (network down,
    # auth failure, rate limit, etc). This must propagate all the way
    # out of run() rather than being swallowed or treated as "no
    # existing receipt, safe to post" -- the __main__ block is the only
    # place that converts it into a visible BLOCKED exit.
    import issue362_work_receipt_probe as probe

    calls = []

    def flaky_api(method, path, body=None):
        calls.append((method, path, body))
        raise RuntimeError("GitHub API failed; check authentication, permissions and network")

    monkeypatch.setattr(probe, "api", flaky_api)
    with pytest.raises(RuntimeError, match="GitHub API failed"):
        probe.run(post=True)
    assert all(c[0] != "POST" for c in calls)


def test_run_revalidates_head_immediately_before_and_after_posting(monkeypatch):
    # _check_head is called once right before the POST and once right
    # after the read-back confirms -- if the PR's HEAD moved in between
    # (a push landed mid-run), the second check must still catch it even
    # though the first one passed, rather than confirming a now-stale
    # receipt as valid.
    import issue362_work_receipt_probe as probe

    calls = []
    pr_head_calls = {"count": 0}

    def fake_api(method, path, body=None):
        calls.append((method, path, body))
        if path == f"repos/{REPO}/pulls/362":
            pr_head_calls["count"] += 1
            # First call (top of run()) and the pre-post _check_head call
            # both see the original SHA; the HEAD "moves" only for the
            # post-post _check_head call (the 3rd pulls/362 fetch).
            sha = SHA if pr_head_calls["count"] < 3 else "c" * 40
            return _pr_fixture(sha)
        if path == f"repos/{REPO}/issues/comments/{SOURCE}":
            return _audit_fixture(SHA)
        if path.startswith(f"repos/{REPO}/issues/362/comments") and method == "GET":
            return []
        if method == "POST":
            return {"id": 123456}
        if path == f"repos/{REPO}/issues/comments/123456":
            body_text = (
                f"WORK_AUDIT_RECEIPT_V1 repo={REPO} pr=362 "
                f"source_comment_id={SOURCE} head={SHA} result=VERIFIED\n\n"
                "Verified live GitHub audit record and PR HEAD using bounded local probe. "
                "Does not prove unattended Claude execution."
            )
            return {"id": 123456, "body": body_text}
        raise AssertionError(f"unexpected api call: {method} {path}")

    monkeypatch.setattr(probe, "api", fake_api)
    with pytest.raises(ValueError, match="changed"):
        probe.run(post=True)
    post_calls = [c for c in calls if c[0] == "POST"]
    assert len(post_calls) == 1

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

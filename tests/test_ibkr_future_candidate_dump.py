from pathlib import Path


def test_future_candidate_dump_remains_read_only():
    text = Path(
        "src/ai_asset_platform/brokers/ibkr_future_candidate_dump.py"
    ).read_text(encoding="utf-8")
    assert "placeOrder(" not in text
    assert "cancelOrder(" not in text
    assert "Order()" not in text
    assert "discover_ibkr_paper_futures" in text


def test_future_candidate_dump_wrapper_runs_tests_first():
    text = Path("ibkr_future_candidate_dump_once.sh").read_text(encoding="utf-8")
    assert "python -m pytest -q" in text
    assert "ibkr_future_candidate_dump" in text

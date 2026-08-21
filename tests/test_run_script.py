from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_run_script_delegates_to_existing_start_flow_without_live_unlock():
    text = (ROOT / "scripts" / "run.sh").read_text(encoding="utf-8")
    assert "source .venv/bin/activate" in text
    assert "source .env" in text
    assert "exec bash start.sh" in text
    assert "ENABLE_LIVE" not in text
    assert "LIVE_TRADING" not in text

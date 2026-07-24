from pathlib import Path


def test_start_script_runs_step8_after_setup_check():
    script = Path("start.sh").read_text(encoding="utf-8")

    assert "python setup_wizard.py --check" in script
    assert "source .env" in script
    assert "python main_simple_step8.py" in script

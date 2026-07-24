from pathlib import Path


def test_start_script_runs_main_through_dry_run_entrypoint():
    script = Path("start.sh").read_text(encoding="utf-8")

    assert "python main_simple_step8.py" in script
    assert "BROKER_MODE" in script
    assert "dry_run" in script


def test_start_script_uses_setup_wizard_when_env_missing():
    script = Path("start.sh").read_text(encoding="utf-8")

    assert "python setup_wizard.py --check" in script
    assert "python setup_wizard.py" in script
    assert "source .env" in script

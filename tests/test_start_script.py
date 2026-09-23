from pathlib import Path


def test_start_script_runs_step8_after_safe_setup_and_env_load():
    script = Path("start.sh").read_text(encoding="utf-8")

    setup_index = script.index("python setup_wizard.py --check")
    safe_env_index = script.index("python scripts/load_start_env.py .env")
    second_verify_index = script.rindex("bash scripts/ensure_exact_checkout_runtime.sh")
    step8_index = script.index("python main_simple_step8.py")

    assert "source .env" not in script
    assert "if [ -f .env ]; then" in script
    assert setup_index < safe_env_index < second_verify_index < step8_index

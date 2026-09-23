from pathlib import Path


def test_start_script_runs_step8_after_safe_setup_and_env_load():
    launcher = Path("start.sh").read_text(encoding="utf-8")
    script = Path("scripts/start_sanitized.sh").read_text(encoding="utf-8")

    assert "AI_ASSET_START_SANITIZED" not in launcher
    assert "exec /usr/bin/env -i" in launcher
    setup_index = script.index('"$VENV_PYTHON" setup_wizard.py --check')
    safe_env_index = script.index('"$VENV_PYTHON" scripts/load_start_env.py .env')
    second_verify_index = script.rindex("\nverify_exact_checkout_runtime\n")
    step8_index = script.index('"$VENV_PYTHON" main_simple_step8.py')

    assert "source .env" not in script
    assert "source .venv/bin/activate" not in script
    assert "if [ -f .env ]; then" in script
    assert setup_index < safe_env_index < second_verify_index < step8_index

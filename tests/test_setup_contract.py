from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_setup_and_run_entrypoints_exist():
    assert (ROOT / "scripts" / "setup.sh").is_file()
    assert (ROOT / "scripts" / "run.sh").is_file()
    assert (ROOT / ".env.example").is_file()


def test_setup_runs_test_suite_after_dependency_install():
    text = (ROOT / "scripts" / "setup.sh").read_text(encoding="utf-8")
    assert "requirements.txt" in text
    assert "pytest" in text

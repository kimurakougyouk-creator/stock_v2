from pathlib import Path


def test_required_scripts_exist_and_are_executable():
    for script in ["setup.sh", "check.sh", "run.sh"]:
        path = Path("scripts") / script
        assert path.exists()
        assert path.stat().st_mode & 0o111


def test_env_example_contains_only_required_keys():
    lines = Path(".env.example").read_text().splitlines()

    assert lines == ["EMAIL_ADDRESS=", "APP_PASSWORD="]


def test_check_script_does_not_print_secret_values():
    content = Path("scripts/check.sh").read_text()

    assert "値は表示しません" in content
    assert "${!name}" not in content


def test_check_script_import_probe_stubs_optional_dependencies():
    content = Path("scripts/check.sh").read_text()

    assert "_install_missing_stub" in content
    assert "主要ファイルのimport確認" in content

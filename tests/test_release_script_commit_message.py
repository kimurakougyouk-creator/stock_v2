from pathlib import Path


def test_release_script_accepts_commit_message_argument():
    text = Path("release.sh").read_text(encoding="utf-8")

    assert 'COMMIT_MESSAGE="${1:-}"' in text


def test_release_script_keeps_manual_fallback():
    text = Path("release.sh").read_text(encoding="utf-8")

    assert 'read -r -p "コミットメッセージを入力してください:' in text


def test_release_script_still_runs_tests_before_commit():
    text = Path("release.sh").read_text(encoding="utf-8")

    pytest_position = text.index('"$PYTHON" -m pytest -q')
    commit_position = text.index('git commit -m "$COMMIT_MESSAGE"')

    assert pytest_position < commit_position

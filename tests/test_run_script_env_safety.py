from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_real_env_is_ignored_while_example_is_trackable():
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "\n.env\n" in "\n" + gitignore
    assert (ROOT / ".env.example").is_file()

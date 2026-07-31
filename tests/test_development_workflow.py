from pathlib import Path

from ai_asset_platform.developer.workflow import run_development_workflow


def test_workflow_import() -> None:
    assert callable(run_development_workflow)

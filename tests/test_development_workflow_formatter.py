from ai_asset_platform.developer.workflow_formatter import format_workflow_status
from ai_asset_platform.developer.workflow_status import DevelopmentWorkflowStatus


def test_format_workflow_status():
    status = DevelopmentWorkflowStatus(
        planning=True,
        ready=True,
        task_created=True,
        report_created=False,
        summary_created=False,
    )

    assert format_workflow_status(status) == "Progress: 60% (3/5)"

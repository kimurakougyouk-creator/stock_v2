from ai_asset_platform.developer.workflow_export import export_workflow_status
from ai_asset_platform.developer.workflow_status import DevelopmentWorkflowStatus


def test_export_workflow_status():
    status = DevelopmentWorkflowStatus(
        planning=True,
        ready=True,
        task_created=True,
        report_created=False,
        summary_created=False,
    )

    exported = export_workflow_status(status)

    assert exported["completed_steps"] == 3
    assert exported["total_steps"] == 5
    assert exported["progress_percent"] == 60
    assert exported["planning"] is True
    assert exported["summary_created"] is False

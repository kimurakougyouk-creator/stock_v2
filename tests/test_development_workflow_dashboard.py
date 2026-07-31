from ai_asset_platform.developer.workflow_dashboard import create_workflow_dashboard
from ai_asset_platform.developer.workflow_status import DevelopmentWorkflowStatus


def test_create_workflow_dashboard():
    status = DevelopmentWorkflowStatus(
        planning=True,
        ready=True,
        task_created=True,
        report_created=False,
        summary_created=False,
    )

    dashboard = create_workflow_dashboard(status)

    assert dashboard["completed_steps"] == 3
    assert dashboard["total_steps"] == 5
    assert dashboard["progress_percent"] == 60

from ai_asset_platform.developer.workflow_status import DevelopmentWorkflowStatus


def test_progress_percent():
    status = DevelopmentWorkflowStatus(
        planning=True,
        ready=True,
        task_created=True,
        report_created=False,
        summary_created=False,
    )

    assert status.completed_steps == 3
    assert status.total_steps == 5
    assert status.progress_percent == 60


def test_progress_completed():
    status = DevelopmentWorkflowStatus(
        planning=True,
        ready=True,
        task_created=True,
        report_created=True,
        summary_created=True,
    )

    assert status.progress_percent == 100

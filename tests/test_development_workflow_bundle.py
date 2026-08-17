from ai_asset_platform.developer.workflow_bundle import DevelopmentWorkflowBundle
from ai_asset_platform.developer.workflow_status import DevelopmentWorkflowStatus


def test_workflow_bundle_as_dict():
    status = DevelopmentWorkflowStatus(
        planning=True,
        ready=True,
        task_created=True,
        report_created=False,
        summary_created=False,
    )

    bundle = DevelopmentWorkflowBundle(status)

    assert bundle.as_dict() == {
        "completed_steps": 3,
        "total_steps": 5,
        "progress_percent": 60,
        "planning": True,
        "ready": True,
        "task_created": True,
        "report_created": False,
        "summary_created": False,
    }

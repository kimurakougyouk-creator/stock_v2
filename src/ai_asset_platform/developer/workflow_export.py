from ai_asset_platform.developer.workflow_status import DevelopmentWorkflowStatus


def export_workflow_status(status: DevelopmentWorkflowStatus) -> dict:
    return {
        "completed_steps": status.completed_steps,
        "total_steps": status.total_steps,
        "progress_percent": status.progress_percent,
        "planning": status.planning,
        "ready": status.ready,
        "task_created": status.task_created,
        "report_created": status.report_created,
        "summary_created": status.summary_created,
    }

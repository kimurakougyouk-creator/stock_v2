from ai_asset_platform.developer.workflow_status import DevelopmentWorkflowStatus


def create_workflow_dashboard(status: DevelopmentWorkflowStatus) -> dict:
    return {
        "completed_steps": status.completed_steps,
        "total_steps": status.total_steps,
        "progress_percent": status.progress_percent,
    }

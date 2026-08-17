from ai_asset_platform.developer.workflow_status import DevelopmentWorkflowStatus


def format_workflow_status(status: DevelopmentWorkflowStatus) -> str:
    return (
        f"Progress: {status.progress_percent}% "
        f"({status.completed_steps}/{status.total_steps})"
    )

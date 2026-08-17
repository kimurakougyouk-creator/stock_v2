"""Workflow summary utilities."""


def summarize_workflow(workflow):
    """Summarize workflow status counts."""

    total = len(workflow)
    completed = sum(
        1 for item in workflow if item.get("status") == "completed"
    )
    pending = sum(
        1 for item in workflow if item.get("status") == "pending"
    )

    return {
        "total": total,
        "completed": completed,
        "pending": pending,
    }

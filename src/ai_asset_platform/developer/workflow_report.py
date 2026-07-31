def create_workflow_report(
    plan: str,
    priority: str,
    readiness: bool,
    task: str,
) -> str:
    status = "READY" if readiness else "NOT READY"

    return (
        f"Plan: {plan}\n"
        f"Priority: {priority}\n"
        f"Status: {status}\n"
        f"Task: {task}"
    )

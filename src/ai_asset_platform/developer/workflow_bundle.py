from dataclasses import dataclass

from ai_asset_platform.developer.workflow_status import DevelopmentWorkflowStatus


@dataclass(frozen=True)
class DevelopmentWorkflowBundle:
    status: DevelopmentWorkflowStatus

    def as_dict(self) -> dict:
        return {
            "completed_steps": self.status.completed_steps,
            "total_steps": self.status.total_steps,
            "progress_percent": self.status.progress_percent,
            "planning": self.status.planning,
            "ready": self.status.ready,
            "task_created": self.status.task_created,
            "report_created": self.status.report_created,
            "summary_created": self.status.summary_created,
        }

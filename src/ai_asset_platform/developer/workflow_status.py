from dataclasses import dataclass


@dataclass(frozen=True)
class DevelopmentWorkflowStatus:
    planning: bool
    ready: bool
    task_created: bool
    report_created: bool
    summary_created: bool

    @property
    def completed_steps(self) -> int:
        return sum(
            (
                self.planning,
                self.ready,
                self.task_created,
                self.report_created,
                self.summary_created,
            )
        )

    @property
    def total_steps(self) -> int:
        return 5

    @property
    def progress_percent(self) -> int:
        return int(self.completed_steps / self.total_steps * 100)

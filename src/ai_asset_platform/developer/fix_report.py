from dataclasses import dataclass

from ai_asset_platform.developer.fix_reason import FixReason


@dataclass(frozen=True)
class FixReport:
    """修正レポート"""

    title: str
    priority: int
    reason: str


def create_fix_report(reason: FixReason, priority: int) -> FixReport:
    """修正レポートを作成する"""

    return FixReport(
        title=reason.title,
        priority=priority,
        reason=reason.reason,
    )


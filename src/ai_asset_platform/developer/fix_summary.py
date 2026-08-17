from dataclasses import dataclass

from ai_asset_platform.developer.fix_report import FixReport


@dataclass(frozen=True)
class FixSummary:
    """修正内容のサマリー"""

    total_items: int
    highest_priority: int
    titles: list[str]


def create_fix_summary(reports: list[FixReport]) -> FixSummary:
    """修正レポートの一覧からサマリーを作成する"""

    if not reports:
        return FixSummary(
            total_items=0,
            highest_priority=0,
            titles=[],
        )

    return FixSummary(
        total_items=len(reports),
        highest_priority=max(report.priority for report in reports),
        titles=[report.title for report in reports],
    )

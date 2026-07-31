from ai_asset_platform.developer.fix_report import FixReport


def create_fix_dashboard(reports: list[FixReport]) -> str:
    """修正レポートを見やすい文字列にまとめる"""

    if not reports:
        return "No fixes."

    lines = []

    for report in reports:
        lines.append(
            f"[Priority {report.priority}] {report.title}\n"
            f"Reason: {report.reason}"
        )

    return "\n\n".join(lines)

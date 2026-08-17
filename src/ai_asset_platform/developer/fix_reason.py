from dataclasses import dataclass


@dataclass(frozen=True)
class FixReason:
    """修正候補を選んだ理由"""

    title: str
    reason: str


def create_fix_reason(title: str, priority: int) -> FixReason:
    """優先度から修正理由を生成する"""

    if priority >= 90:
        reason = "最優先で対応すべき重要な修正です。"
    elif priority >= 70:
        reason = "優先度が高く、早めの対応が望まれます。"
    elif priority >= 50:
        reason = "通常の優先度で対応します。"
    else:
        reason = "緊急性は低いため、後で対応できます。"

    return FixReason(title=title, reason=reason)

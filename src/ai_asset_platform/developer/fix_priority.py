from dataclasses import dataclass


@dataclass(frozen=True)
class FixSuggestion:
    title: str
    severity: str


_PRIORITY = {
    "critical": 0,
    "high": 1,
    "medium": 2,
    "low": 3,
}


def prioritize_fixes(fixes: list[FixSuggestion]) -> list[FixSuggestion]:
    """
    修正候補を重要度順に並べ替える。
    同じ重要度の場合はタイトル順に並べる。
    """
    return sorted(
        fixes,
        key=lambda fix: (
            _PRIORITY.get(fix.severity.lower(), 999),
            fix.title.lower(),
        ),
    )

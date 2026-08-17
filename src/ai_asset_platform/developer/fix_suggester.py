from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class FixSuggestion:
    """修正候補"""

    title: str
    reason: str


def suggest_fixes(issues: Iterable[str]) -> list[FixSuggestion]:
    """
    問題点一覧から修正候補を生成する。
    """

    suggestions: list[FixSuggestion] = []

    for issue in issues:
        text = issue.lower()

        if "long" in text:
            suggestions.append(
                FixSuggestion(
                    title="関数を分割する",
                    reason="長い関数は保守性を下げるため",
                )
            )

        elif "duplicate" in text:
            suggestions.append(
                FixSuggestion(
                    title="共通化する",
                    reason="重複コードを削減できるため",
                )
            )

        elif "type" in text:
            suggestions.append(
                FixSuggestion(
                    title="型ヒントを追加する",
                    reason="可読性と安全性が向上するため",
                )
            )

        else:
            suggestions.append(
                FixSuggestion(
                    title="コードレビューを行う",
                    reason="自動判定できない問題のため",
                )
            )

    return suggestions

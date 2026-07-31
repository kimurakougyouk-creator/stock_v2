"""Select the highest priority fix candidate."""

from __future__ import annotations

from typing import Any


def select_next_fix(candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Return the highest-priority fix candidate.

    Each candidate should contain a numeric ``priority`` field.
    If the list is empty, return ``None``.
    """

    if not candidates:
        return None

    return max(candidates, key=lambda item: item.get("priority", 0))

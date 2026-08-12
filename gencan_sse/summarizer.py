"""Catch-up summarization for missed events during Away Mode."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from gencan_sse.history import HistoryItem


def generate_catchup_summary(items: list[HistoryItem]) -> str:
    """Generate a concise spoken summary of items logged during Away Mode.

    Args:
        items: List of HistoryItem instances collected while Away Mode was active.

    Returns:
        A natural language summary string ready for speech synthesis.
    """
    if not items:
        return "Welcome back! No new updates were received while you were away."

    total = len(items)
    event_counts: dict[str, int] = {}
    errors: list[str] = []
    messages: list[str] = []
    tool_uses: list[str] = []

    for item in items:
        ev_type = item.event_type.lower() if item.event_type else "message"
        event_counts[ev_type] = event_counts.get(ev_type, 0) + 1

        if ev_type == "error":
            errors.append(item.text)
        elif ev_type == "message":
            messages.append(item.text)
        elif ev_type in ("tool_use", "tool"):
            tool_uses.append(item.text)

    summary_parts = [f"Welcome back! You have {total} update{'s' if total != 1 else ''}."]

    details = []
    if messages:
        details.append(f"{len(messages)} message{'s' if len(messages) != 1 else ''}")
    if tool_uses:
        details.append(f"{len(tool_uses)} tool operation{'s' if len(tool_uses) != 1 else ''}")
    if errors:
        details.append(f"{len(errors)} error{'s' if len(errors) != 1 else ''}")

    if details:
        if len(details) == 1:
            summary_parts.append(f"Including {details[0]}.")
        else:
            summary_parts.append(f"Including {', '.join(details[:-1])} and {details[-1]}.")

    if errors:
        summary_parts.append(f"Latest error: {errors[-1]}")
    elif messages:
        last_msg = messages[-1]
        if len(last_msg) > 120:
            last_msg = last_msg[:117] + "..."
        summary_parts.append(f"Latest message: {last_msg}")

    return " ".join(summary_parts)

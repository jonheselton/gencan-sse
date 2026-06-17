"""Classifier module — parse JSONL events and map to voice categories."""

import json
import logging

from gencan_sse.types import ClassifiedEvent, EventType, Priority

logger = logging.getLogger(__name__)


# Mapping from stream-json event type strings to internal EventType + Priority
_EVENT_MAP: dict[str, tuple[EventType, Priority]] = {
    "message": (EventType.MESSAGE, Priority.RESPONSE),
    "tool_use": (EventType.TOOL_USE, Priority.TOOL),
    "tool_result": (EventType.TOOL_RESULT, Priority.TOOL),
    "error": (EventType.ERROR, Priority.ERROR),
    "thinking": (EventType.THINKING, Priority.THINKING),
}

# Event types that produce no audio
_SKIP_TYPES = {"init", "result"}


def _extract_text(event_type: str, data: dict) -> str:
    """Extract the speakable text from a parsed event based on its type."""
    if event_type == "message":
        return data.get("content", "")
    elif event_type == "tool_use":
        tool_name = data.get("tool", "unknown tool")
        return f"Running {tool_name}"
    elif event_type == "tool_result":
        return data.get("output", "")
    elif event_type == "error":
        return data.get("message", "An error occurred")
    elif event_type == "thinking":
        return data.get("content", "")
    return ""


def classify(raw_line: str) -> ClassifiedEvent:
    """Parse a JSONL line and return a ClassifiedEvent.

    Never raises — returns a SKIP event for any invalid or unrecognized input.

    Args:
        raw_line: A single line of JSON from Gemini CLI stream-json output.

    Returns:
        A ClassifiedEvent with the appropriate type, text, and priority.
    """
    raw_line = raw_line.strip()
    if not raw_line:
        return ClassifiedEvent(
            event_type=EventType.SKIP,
            text="",
            raw={},
            priority=Priority.THINKING,
        )

    try:
        data = json.loads(raw_line)
    except (json.JSONDecodeError, TypeError):
        logger.debug("Failed to parse JSON: %s", raw_line[:100])
        return ClassifiedEvent(
            event_type=EventType.SKIP,
            text="",
            raw={},
            priority=Priority.THINKING,
        )

    if not isinstance(data, dict):
        logger.debug("Parsed JSON is not a dict: %s", type(data))
        return ClassifiedEvent(
            event_type=EventType.SKIP,
            text="",
            raw=data if isinstance(data, dict) else {},
            priority=Priority.THINKING,
        )

    event_type_str = data.get("type", "")

    # Skip types produce no audio
    if event_type_str in _SKIP_TYPES:
        logger.debug("Skipping event type: %s", event_type_str)
        return ClassifiedEvent(
            event_type=EventType.SKIP,
            text="",
            raw=data,
            priority=Priority.THINKING,
        )

    # Map known types
    if event_type_str in _EVENT_MAP:
        event_type, priority = _EVENT_MAP[event_type_str]
        text = _extract_text(event_type_str, data)
        return ClassifiedEvent(
            event_type=event_type,
            text=text,
            raw=data,
            priority=priority,
        )

    # Unknown type — skip
    logger.debug("Unknown event type: %s", event_type_str)
    return ClassifiedEvent(
        event_type=EventType.SKIP,
        text="",
        raw=data,
        priority=Priority.THINKING,
    )

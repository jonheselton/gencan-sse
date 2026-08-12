"""Spoken history buffer and unread tracking for gencan-sse."""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger(__name__)


@dataclass
class HistoryItem:
    """A record of a spoken or synthesized utterance."""
    text: str
    voice: str = "Kore"
    style: str = ""
    event_type: str = "message"
    timestamp: float = field(default_factory=time.time)
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    audio_bytes: Optional[bytes] = None
    was_away: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Convert to a JSON-serializable dictionary (excluding raw audio bytes)."""
        return {
            "id": self.id,
            "text": self.text,
            "voice": self.voice,
            "style": self.style,
            "event_type": self.event_type,
            "timestamp": self.timestamp,
            "was_away": self.was_away,
            "audio_size_bytes": len(self.audio_bytes) if self.audio_bytes else 0,
        }


class SpokenHistoryBuffer:
    """Thread-safe circular buffer storing recent spoken utterances."""

    def __init__(self, capacity: int = 50) -> None:
        self.capacity = capacity
        self._items: list[HistoryItem] = []
        self._unread_count: int = 0

    def add_item(self, item: HistoryItem) -> None:
        """Add an item to the history buffer."""
        self._items.append(item)
        if item.was_away:
            self._unread_count += 1

        # Maintain capacity limit
        if len(self._items) > self.capacity:
            removed = self._items.pop(0)
            # If a dropped item was unread, adjust count
            if removed.was_away and self._unread_count > 0:
                self._unread_count -= 1

    def get_recent(self, count: int = 10, unread_only: bool = False) -> list[HistoryItem]:
        """Retrieve recent items from history."""
        if unread_only:
            items = [item for item in self._items if item.was_away]
            return items[-count:] if count > 0 else items
        return self._items[-count:] if count > 0 else list(self._items)

    def get_unread(self) -> list[HistoryItem]:
        """Get all unread items recorded while in Away Mode."""
        return [item for item in self._items if item.was_away]

    def mark_all_read(self) -> None:
        """Mark all unread items as read."""
        for item in self._items:
            item.was_away = False
        self._unread_count = 0

    @property
    def unread_count(self) -> int:
        """Number of unread items."""
        return self._unread_count

    @property
    def total_count(self) -> int:
        """Total items stored in history."""
        return len(self._items)

    def to_dict_list(self, limit: int = 50) -> list[dict[str, Any]]:
        """Return history items as dictionaries."""
        recent = self.get_recent(count=limit)
        return [item.to_dict() for item in recent]
